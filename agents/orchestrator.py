"""Self-healing loop orchestration as a LangGraph state machine.

The graph wires the four agents into the detect -> diagnose -> plan -> execute pipeline
from the design note. It is invoked once per simulation tick; cross-tick timing
(debounce, cooldown, recovery wait) lives in the persistent HealingState, so a single
graph drives the whole loop incrementally as the Streamlit app advances.

Routing per tick:
    detector --> (anomaly sustained 3 ticks, not in cooldown) --> diagnosis
    diagnosis --> planner            (auto-heal ON)
              --> END                (auto-heal OFF: stop, await manual approval)
    planner   --> executor           (approved)
              --> END                (rejected: failed)
    executor  --> END                (fix applied; recovery confirmed on later ticks)
    detector --> recovery            (status == executing)
    detector --> executor            (status == awaiting_approval AND user approved)

Live references (graph, store, kg, auto-heal flag, approve flag) ride in state["ctx"];
`active_faults` is a top-level state field because the Executor rewrites it.
"""

from typing import TypedDict

from langgraph.graph import END, StateGraph

from agents import detector, diagnosis as diagnosis_agent, executor, planner as planner_agent
from knowledge.queries import find_remediation

DEBOUNCE = 3    # ticks of sustained violation before diagnosing (suppresses noise spikes)
COOLDOWN = 10   # ticks after a cycle before the detector can re-trigger
RECOVERY_GIVEUP = 12  # ticks after applying a fix before declaring recovery failed


class HealingState(TypedDict):
    tick: int
    anomaly: dict | None
    diagnosis: dict | None
    plan: dict | None
    execution: dict | None
    status: str
    trace: list[dict]
    # cross-tick bookkeeping
    debounce_count: int
    cooldown_remaining: int
    apply_tick: int | None
    pending_action: dict | None
    last_detect_tick: int
    active_faults: list
    ctx: dict


def initial_state() -> HealingState:
    """Fresh idle state for a new session."""
    return {
        "tick": 0, "anomaly": None, "diagnosis": None, "plan": None, "execution": None,
        "status": "idle", "trace": [], "debounce_count": 0, "cooldown_remaining": 0,
        "apply_tick": None, "pending_action": None, "last_detect_tick": -1,
        "active_faults": [], "ctx": {},
    }


# --------------------------------------------------------------------------- nodes


def _detector_node(state: HealingState) -> dict:
    """Run rule-based detection; manage debounce and cooldown (once per new tick)."""
    ctx, tick = state["ctx"], state["tick"]
    if tick == state["last_detect_tick"]:
        return {}  # idempotent across non-tick reruns (e.g. a manual-approval click)

    updates: dict = {"last_detect_tick": tick}
    status = state["status"]
    in_cooldown = state["cooldown_remaining"] > 0
    if in_cooldown:
        cd = state["cooldown_remaining"] - 1
        updates["cooldown_remaining"] = cd
        if cd == 0 and status in ("resolved", "failed"):
            updates["status"] = "idle"
        return updates

    out = detector.run(ctx["graph"], ctx["store"], tick)
    if status in ("idle", "detecting"):
        if out["anomaly_detected"]:
            dc = state["debounce_count"] + 1
            updates["debounce_count"] = dc
            updates["status"] = "detecting"
            if dc >= DEBOUNCE:
                updates["anomaly"] = out
        else:
            updates["debounce_count"] = 0
            if status == "detecting":
                updates["status"] = "idle"
    return updates


def _diagnosis_node(state: HealingState) -> dict:
    """Diagnose the confirmed anomaly; start a fresh trace for this cycle."""
    ctx = state["ctx"]
    anomaly = state["anomaly"]
    diag = diagnosis_agent.diagnose(ctx["kg"], ctx["graph"], ctx["store"], anomaly)

    trace = [
        {"step": "detection", "tick": anomaly["tick"], "violations": anomaly["violations"]},
        {"step": "diagnosis", "tick": state["tick"], **diag},
    ]
    updates = {"diagnosis": diag, "status": "diagnosing", "trace": trace, "plan": None,
               "execution": None, "pending_action": None}

    if not ctx["auto_heal"]:
        rec = find_remediation(ctx["kg"], diag["root_cause"])
        trace.append({"step": "recommendation", "tick": state["tick"], **rec})
        updates["status"] = "awaiting_approval"
        updates["pending_action"] = rec
    return updates


def _planner_node(state: HealingState) -> dict:
    """Verify the KG-recommended remediation against the dependency graph."""
    ctx = state["ctx"]
    p = planner_agent.plan(ctx["kg"], ctx["graph"], state["diagnosis"])
    trace = state["trace"] + [{"step": "planning", "tick": state["tick"], **p}]
    updates = {"plan": p, "status": "planning", "trace": trace}
    if not p["approved"]:
        updates["status"] = "failed"
        updates["cooldown_remaining"] = COOLDOWN
        trace.append({
            "step": "execution", "tick": state["tick"], "action_taken": p["action"],
            "applied": False, "success": False,
            "note": "Planner rejected the action; no change applied.",
        })
    return updates


def _executor_node(state: HealingState) -> dict:
    """Apply the approved fix to the twin (deterministic); recovery confirmed later."""
    ctx = state["ctx"]
    source = state["plan"] or state["pending_action"]
    action = source["action"]
    new_faults = executor.apply_action(action, state["active_faults"])

    trace = state["trace"] + [{
        "step": "execution", "tick": state["tick"], "action_taken": action,
        "applied": True, "success": None,
    }]
    return {
        "status": "executing", "apply_tick": state["tick"], "active_faults": new_faults,
        "trace": trace,
        "execution": {"action_taken": action, "success": None, "recovery_ticks": None, "post_state": {}},
    }


def _recovery_node(state: HealingState) -> dict:
    """Confirm the affected entities returned to healthy after the fix."""
    ctx = state["ctx"]
    affected = state["diagnosis"]["affected_entities"]
    elapsed = state["tick"] - state["apply_tick"]
    recovered = executor.is_recovered(ctx["graph"], ctx["store"], affected)

    if elapsed >= executor.RECOVERY_WAIT and recovered:
        success, status = True, "resolved"
    elif elapsed >= RECOVERY_GIVEUP:
        success, status = False, "failed"
    else:
        return {}  # still waiting

    snapshot = executor.post_state(ctx["graph"], ctx["store"], affected)
    execution = {**state["execution"], "success": success, "recovery_ticks": elapsed, "post_state": snapshot}
    trace = [dict(e) for e in state["trace"]]
    for entry in reversed(trace):  # finalise the pending execution entry
        if entry["step"] == "execution" and entry.get("success") is None:
            entry["success"] = success
            entry["recovery_ticks"] = elapsed
            entry["post_state"] = snapshot
            break
    return {"status": status, "execution": execution, "trace": trace, "cooldown_remaining": COOLDOWN}


# --------------------------------------------------------------------------- routing


def _route_after_detector(state: HealingState) -> str:
    status = state["status"]
    if status == "executing":
        return "recovery"
    if status == "awaiting_approval":
        return "executor" if state["ctx"].get("approve") else END
    if status == "detecting" and state["debounce_count"] >= DEBOUNCE and state["anomaly"]:
        return "diagnosis"
    return END


def _route_after_diagnosis(state: HealingState) -> str:
    return "planner" if state["ctx"]["auto_heal"] else END


def _route_after_planner(state: HealingState) -> str:
    return "executor" if state["plan"]["approved"] else END


def _build():
    g = StateGraph(HealingState)
    g.add_node("detector", _detector_node)
    g.add_node("diagnosis", _diagnosis_node)
    g.add_node("planner", _planner_node)
    g.add_node("executor", _executor_node)
    g.add_node("recovery", _recovery_node)

    g.set_entry_point("detector")
    g.add_conditional_edges("detector", _route_after_detector,
                            {"diagnosis": "diagnosis", "executor": "executor", "recovery": "recovery", END: END})
    g.add_conditional_edges("diagnosis", _route_after_diagnosis, {"planner": "planner", END: END})
    g.add_conditional_edges("planner", _route_after_planner, {"executor": "executor", END: END})
    g.add_edge("executor", END)
    g.add_edge("recovery", END)
    return g.compile()


graph_app = _build()


def step(state: HealingState, tick: int, graph, store, kg, active_faults: list,
         auto_heal: bool, approve: bool = False) -> HealingState:
    """Advance the healing state machine one invocation. Returns the new state."""
    state = {
        **state,
        "tick": tick,
        "active_faults": active_faults,
        "ctx": {"graph": graph, "store": store, "kg": kg, "auto_heal": auto_heal, "approve": approve},
    }
    return graph_app.invoke(state)

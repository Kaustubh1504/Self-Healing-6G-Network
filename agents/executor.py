"""Executor agent — applies the approved fix to the twin and confirms recovery.

Deterministic by design (no LLM): execution is a fixed mapping from remediation action
to twin operation. Each demo remediation clears the corresponding active fault; the twin
then heals on its own as telemetry resumes normal generation. Recovery is confirmed by
re-reading the affected entities' status a few ticks later.

Output (assembled by the orchestrator once recovery is checked):
    {"action_taken", "success", "recovery_ticks", "post_state"}
"""

from twin import faults
from twin.network import HEALTHY

RECOVERY_WAIT = 5   # ticks to wait after applying before confirming recovery

# Remediation action -> the fault scenario it clears.
_ACTION_TO_FAULT = {
    "isolate_frequency_band": "jammer",
    "offload_traffic": "congestion",
    "offload_to_edge_cloud": "node_overload",
    "restart_network_function": "service_down",
    "reroute_traffic": "sla_breach",
}


def apply_action(action: str, active_faults: list) -> list:
    """Clear the fault corresponding to `action`, returning the new active-faults list."""
    fault_name = _ACTION_TO_FAULT.get(action)
    return faults.remove_fault(active_faults, fault_name) if fault_name else active_faults


def is_recovered(graph, store: dict, affected_entities: list[str]) -> bool:
    """True once every affected node has returned to HEALTHY in the latest sample."""
    for e in affected_entities:
        if e not in graph:
            continue
        df = store.get(e)
        if df is None or df.empty:
            return False
        if df.iloc[-1].get("status") != HEALTHY:
            return False
    return True


def post_state(graph, store: dict, affected_entities: list[str]) -> dict:
    """Latest snapshot of the affected nodes, for the recovery trace entry."""
    snapshot = {}
    for e in affected_entities:
        if e in graph:
            df = store.get(e)
            if df is not None and not df.empty:
                row = df.iloc[-1]
                snapshot[e] = {
                    "status": row.get("status"),
                    "cpu_pct": round(float(row["cpu_pct"]), 1),
                    "memory_pct": round(float(row["memory_pct"]), 1),
                }
    return snapshot

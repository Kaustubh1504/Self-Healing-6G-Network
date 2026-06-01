"""6G Self-Healing Network — Phase 1 digital twin dashboard.

A live, demoable Streamlit view of a 6G-inspired network: an interactive topology,
streaming telemetry, and sidebar fault injection. No agents yet (Phase 2).

Run with:  streamlit run app.py
"""

import contextlib

import streamlit as st
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh

load_dotenv()  # read OPENAI_API_KEY from .env before the agents check for it

from agents import _llm, orchestrator
from knowledge.ontology import build_kg
from twin import faults, telemetry
from twin.network import build_network
from ui import reasoning_trace
from ui.telemetry_chart import build_telemetry_figure
from ui.topology import build_topology_figure

st.set_page_config(page_title="6G Self-Healing Network", layout="wide")

WARMUP_TICKS = 25


def _step(advance: bool) -> None:
    """Expire finished faults and, if advancing, generate one new telemetry tick."""
    st.session_state.active_faults = [
        f for f in st.session_state.active_faults
        if not faults.is_expired(f, st.session_state.tick)
    ]
    if advance:
        st.session_state.tick += 1
        telemetry.tick(
            st.session_state.graph,
            st.session_state.store,
            st.session_state.tick,
            st.session_state.active_faults,
        )


def _init_state() -> None:
    """Build the twin once and warm up the rolling telemetry window."""
    if "graph" in st.session_state:
        return
    graph = build_network()
    st.session_state.graph = graph
    st.session_state.store = telemetry.init_store(graph)
    st.session_state.tick = 0
    st.session_state.running = True
    st.session_state.active_faults = []
    st.session_state.fault_ticks = []
    st.session_state.selected = "BS2-UE2"  # a radio edge replaying a real trace
    st.session_state.speed = 0.6
    # Phase 2: knowledge graph + self-healing agent loop.
    st.session_state.kg = build_kg()
    st.session_state.healing = orchestrator.initial_state()
    st.session_state.auto_heal = False
    st.session_state.approve_clicked = False
    for _ in range(WARMUP_TICKS):
        _step(advance=True)


def _parse_selection(event) -> str | None:
    """Extract the clicked entity id (customdata) from a plotly selection event."""
    try:
        points = event["selection"]["points"]
    except (TypeError, KeyError):
        return None
    for point in points:
        cd = point.get("customdata")
        if cd:
            return cd[0] if isinstance(cd, list) else cd
    return None


_init_state()
graph = st.session_state.graph

# ----- Sidebar: controls + fault injection -----
with st.sidebar:
    st.title("6G Self-Healing")
    st.caption("Phase 1 — radio edges replay real TelecomTS 5G traces")

    toggle = "⏸ Pause" if st.session_state.running else "▶ Start"
    if st.button(toggle, use_container_width=True):
        st.session_state.running = not st.session_state.running
        st.rerun()

    st.session_state.speed = st.slider("Seconds per tick", 0.2, 2.0, st.session_state.speed, 0.1)
    st.metric("Tick", st.session_state.tick)

    st.subheader("Self-healing")
    key_available = _llm.available()
    if not key_available:
        st.session_state.auto_heal = False
    st.toggle(
        "Auto-heal (autonomous)",
        key="auto_heal",
        disabled=not key_available,
        help="ON: the loop detects, diagnoses, plans and executes fixes autonomously. "
             "OFF: detection + diagnosis run, then you approve the fix manually.",
    )
    st.caption("Inject a fault (below) to see the agents act — the trace appears in the right panel.")
    if not key_available:
        st.warning("Set `OPENAI_API_KEY` to enable LLM reasoning and auto-heal. "
                   "Manual mode still runs (KG-derived diagnosis).")
    if st.session_state.healing["status"] == "awaiting_approval":
        rec = st.session_state.healing["pending_action"]
        if st.button(f"✅ Apply recommended fix: {rec['action']}", use_container_width=True):
            st.session_state.approve_clicked = True
            st.rerun()

    st.subheader("Inject fault")
    for name in faults.SCENARIO_NAMES:
        if st.button(f"⚠ {faults.scenario_label(name)}", use_container_width=True, key=f"fault_{name}"):
            st.session_state.active_faults.append(faults.make_fault(name, st.session_state.tick))
            st.session_state.fault_ticks.append(st.session_state.tick)
            st.rerun()

    if st.session_state.active_faults:
        st.subheader("Active faults")
        for f in st.session_state.active_faults:
            remaining = f.duration_ticks - (st.session_state.tick - f.start_tick)
            st.write(f"• {f.label} — {max(0, remaining)} ticks left")

# ----- Live updating: browser-driven refresh, one sim tick per interval -----
if st.session_state.running:
    count = st_autorefresh(interval=int(st.session_state.speed * 1000), key="sim_tick")
    if count != st.session_state.get("last_tick_count"):
        st.session_state.last_tick_count = count
        _step(advance=True)

# ----- Self-healing loop: invoke the agent orchestrator each run (idempotent per tick) -----
approve = st.session_state.approve_clicked
st.session_state.approve_clicked = False
# Show feedback while the LLM agents reason (the step call blocks during those calls).
_busy = st.session_state.active_faults and st.session_state.healing["status"] in (
    "detecting", "diagnosing", "planning", "awaiting_approval",
)
_spinner = st.spinner("🧠 Agents reasoning…") if _busy else contextlib.nullcontext()
try:
    with _spinner:
        st.session_state.healing = orchestrator.step(
            st.session_state.healing,
            st.session_state.tick,
            graph,
            st.session_state.store,
            st.session_state.kg,
            st.session_state.active_faults,
            auto_heal=st.session_state.auto_heal and _llm.available(),
            approve=approve,
        )
    st.session_state.healing_error = None
except Exception as exc:  # surface it in the panel instead of freezing the loop
    import traceback
    st.session_state.healing_error = traceback.format_exc()
st.session_state.active_faults = st.session_state.healing["active_faults"]

# ----- Main: network view (left) + agent healing drawer (right) -----
main_col, healing_col = st.columns([2, 1], gap="large")

with main_col:
    st.subheader("Network topology")
    topo_fig = build_topology_figure(graph, st.session_state.selected)
    event = st.plotly_chart(
        topo_fig,
        use_container_width=True,
        key="topology",
        on_select="rerun",
        selection_mode="points",
    )
    clicked = _parse_selection(event)
    if clicked and clicked != st.session_state.selected:
        st.session_state.selected = clicked
        st.rerun()

    st.caption(f"Selected: **{st.session_state.selected}** — click a node or edge marker to inspect it.")

    st.subheader("Telemetry")
    selected = st.session_state.selected
    real_edges = {faults.edge_id(u, v) for u, v, d in graph.edges(data=True) if "traces" in d}
    if selected in st.session_state.store:
        if selected in real_edges:
            st.caption("📡 Data source: **real TelecomTS 5G trace**")
        else:
            st.caption("🔧 Data source: **synthetic**")
        tele_fig = build_telemetry_figure(
            st.session_state.store[selected], selected, st.session_state.fault_ticks
        )
        st.plotly_chart(tele_fig, use_container_width=True, key="telemetry")
    else:
        st.info("Select a node or edge to view its telemetry.")

# ----- Reasoning trace: the self-healing agent pipeline, step by step -----
with healing_col:
    st.subheader("🧠 Agent self-healing")
    if st.session_state.get("healing_error"):
        st.error("Healing loop error (the agents hit an exception):")
        st.code(st.session_state.healing_error)
    reasoning_trace.render(st.session_state.healing, st.session_state.kg)

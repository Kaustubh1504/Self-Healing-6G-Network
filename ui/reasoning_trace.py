"""Reasoning trace panel: the agent pipeline's output, step by step.

Renders each agent's contribution to a healing cycle as a colour-coded expander
(detection -> diagnosis -> planning -> execution), with the matched knowledge-graph
path drawn inline inside the Diagnosis step.
"""

import plotly.graph_objects as go
import streamlit as st

from agents import orchestrator
from knowledge.queries import kg_path

# Reasoning trace colours (per the project style guide).
_COLORS = {
    "detection": "#FFAA00",
    "diagnosis": "#4A9EFF",
    "recommendation": "#AA66FF",
    "planning": "#AA66FF",
    "execution": "#00CC66",
}

_STATUS_BLURB = {
    "idle": "🟢 Idle — monitoring telemetry",
    "detecting": "🟡 Anomaly detected — confirming (debounce)",
    "diagnosing": "🔵 Diagnosing root cause",
    "planning": "🟣 Planning remediation",
    "awaiting_approval": "⏸ Awaiting manual approval",
    "executing": "🟢 Fix applied — confirming recovery",
    "resolved": "✅ Resolved",
    "failed": "❌ Healing failed",
}


def _kg_path_figure(kg, root_cause: str) -> go.Figure | None:
    """Small directed graph of the matched AlarmPattern -> RootCause -> Remediation chain."""
    path = kg_path(kg, root_cause)
    if not path:
        return None

    chain = [
        (path["alarm_pattern"], "Alarm pattern", "#FFAA00", 0.0),
        (path["root_cause"], "Root cause", "#4A9EFF", 1.0),
        (path["remediation_label"], "Remediation", "#00CC66", 2.0),
    ]
    fig = go.Figure()

    # Edges along the chain, labelled with the KG predicate.
    for (a, _, _, xa), (b, _, _, xb), pred in zip(chain, chain[1:], ("indicates", "resolvedBy")):
        fig.add_trace(go.Scatter(x=[xa, xb], y=[1, 1], mode="lines",
                                 line=dict(color="#888", width=2), hoverinfo="skip", showlegend=False))
        fig.add_annotation(x=(xa + xb) / 2, y=1.12, text=f"<i>{pred}</i>", showarrow=False,
                           font=dict(size=10, color="#AAA"))

    for label, role, color, x in chain:
        fig.add_trace(go.Scatter(
            x=[x], y=[1], mode="markers+text", text=[f"<b>{label}</b>"], textposition="bottom center",
            marker=dict(size=26, color=color, line=dict(color="white", width=1.5)),
            hovertext=role, hoverinfo="text", textfont=dict(size=12, color="#EEE"), showlegend=False,
        ))

    # Affected entities branch off the root cause (TEL:affects).
    affected = path["affected_entities"]
    for i, ent in enumerate(affected):
        ex = 1.0 + (i - (len(affected) - 1) / 2) * 0.5
        fig.add_trace(go.Scatter(x=[1.0, ex], y=[1, 0.3], mode="lines",
                                 line=dict(color="#555", width=1, dash="dot"), hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=[ex], y=[0.3], mode="markers+text", text=[ent], textposition="bottom center",
                                 marker=dict(size=12, color="#666"), textfont=dict(size=10, color="#BBB"),
                                 hovertext="affected entity", hoverinfo="text", showlegend=False))
    if affected:
        fig.add_annotation(x=1.0, y=0.66, text="<i>affects</i>", showarrow=False, font=dict(size=10, color="#AAA"))

    fig.update_layout(template="plotly_dark", height=210, margin=dict(l=10, r=10, t=20, b=10),
                      xaxis=dict(visible=False, range=[-0.5, 2.7]), yaxis=dict(visible=False, range=[0.0, 1.3]))
    return fig


def _detection(e: dict) -> None:
    lines = [f"`{v['entity']}` {v['metric']} = **{v['value']}** (threshold {v['threshold']})" for v in e["violations"]]
    st.markdown(f"⚠ **Anomaly detected at tick {e['tick']}** — {len(lines)} violation(s):")
    st.markdown("\n".join(f"- {ln}" for ln in lines))


def _diagnosis(e: dict, kg) -> None:
    st.markdown(f"🔍 **Root cause: `{e['root_cause']}`**  (confidence {e['confidence']:.2f})")
    st.markdown(e["reasoning"])
    st.caption("Knowledge-graph evidence:")
    st.markdown("\n".join(f"- {ev}" for ev in e["kg_evidence"]))
    fig = _kg_path_figure(kg, e["root_cause"])
    if fig is not None:
        st.caption("Matched knowledge-graph path:")
        st.plotly_chart(fig, use_container_width=True, key=f"kgpath_{e['tick']}")


def _recommendation(e: dict) -> None:
    st.markdown(f"📋 **Recommended action: `{e['action']}`** — {e['description']}")
    st.markdown(f"Target entities: {', '.join(e['target_entities'])}")
    st.info("Auto-heal is OFF — click **Apply recommended fix** in the sidebar to execute.")


def _planning(e: dict) -> None:
    verdict = "✅ Approved" if e["approved"] else "❌ Rejected"
    st.markdown(f"📋 **Proposed action: `{e['action']}`** — {verdict}")
    st.markdown(e["verification_reasoning"])
    if e.get("predicted_outcome"):
        st.caption(f"Predicted outcome: {e['predicted_outcome']}")


def _execution(e: dict) -> None:
    if e.get("applied") is False:
        st.markdown(f"❌ **Not applied** — {e.get('note', 'action rejected')}")
        return
    if e.get("success") is None:
        st.markdown(f"⏳ **Action `{e['action_taken']}` applied at tick {e['tick']}** — confirming recovery…")
        return
    if e["success"]:
        post = ", ".join(f"{k} {v['status']}" for k, v in e.get("post_state", {}).items())
        st.markdown(f"✅ **Recovered in {e['recovery_ticks']} ticks** via `{e['action_taken']}`. {post}")
    else:
        st.markdown(f"❌ **Recovery not confirmed** after applying `{e['action_taken']}`.")


_RENDERERS = {
    "detection": _detection,
    "recommendation": _recommendation,
    "planning": _planning,
    "execution": _execution,
}

_TITLES = {
    "detection": "Detection",
    "diagnosis": "Diagnosis",
    "recommendation": "Recommendation",
    "planning": "Planning",
    "execution": "Execution",
}


def render(state: dict, kg) -> None:
    """Render the current healing status and the step-by-step reasoning trace."""
    status = state["status"]
    st.markdown(f"**Self-healing status:** {_STATUS_BLURB.get(status, status)}")

    # Always-visible diagnostics so the loop's state is observable at a glance.
    n_faults = len(state.get("active_faults", []))
    diag = f"tick {state.get('tick', 0)} · {n_faults} active fault(s)"
    if status in ("idle", "detecting") and state.get("debounce_count"):
        diag += f" · confirming {state['debounce_count']}/{orchestrator.DEBOUNCE}"
    if state.get("cooldown_remaining"):
        diag += f" · cooldown {state['cooldown_remaining']}"
    st.caption(diag)

    trace = state["trace"]
    if not trace:
        st.info("No healing cycle yet.\n\n**Inject a fault** from the sidebar (with the sim "
                "running) to start the detect → diagnose → plan → execute loop. The agents' "
                "reasoning will appear here.")
        return

    for i, entry in enumerate(trace):
        step = entry["step"]
        color = _COLORS.get(step, "#888")
        title = f"{_TITLES.get(step, step)} · tick {entry['tick']}"
        with st.expander(title, expanded=(i >= len(trace) - 2)):
            st.markdown(f"<div style='border-left:3px solid {color};padding-left:10px'>", unsafe_allow_html=True)
            if step == "diagnosis":
                _diagnosis(entry, kg)
            else:
                _RENDERERS[step](entry)
            st.markdown("</div>", unsafe_allow_html=True)

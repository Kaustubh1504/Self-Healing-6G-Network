"""Plotly time-series panel for a selected node or edge.

Shows the rolling window of telemetry, one metric per stacked subplot, with dashed
vertical markers at the ticks where faults were injected.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_METRIC_COLOR = {
    "cpu_pct": "#5B8FF9",
    "memory_pct": "#61DDAA",
    "active_sessions": "#65789B",
    "latency_ms": "#F6BD16",
    "throughput_mbps": "#5B8FF9",
    "packet_loss_pct": "#FF6B6B",
    "utilization_pct": "#9270CA",
    "snr_db": "#F6BD16",
    "rsrp_dbm": "#61DDAA",
}

_METRIC_LABEL = {
    "cpu_pct": "CPU %",
    "memory_pct": "Memory %",
    "active_sessions": "Active sessions",
    "latency_ms": "Latency (ms)",
    "throughput_mbps": "Throughput (Mbps)",
    "packet_loss_pct": "Packet loss % (BLER)",
    "utilization_pct": "PRB utilization %",
    "snr_db": "UL SNR (dB)",
    "rsrp_dbm": "RSRP (dBm)",
}


def build_telemetry_figure(df: pd.DataFrame, entity: str, fault_ticks: list[int]) -> go.Figure:
    """Build the stacked time-series figure for `entity` from its telemetry DataFrame."""
    metrics = [c for c in df.columns if c != "tick"]

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark",
            height=360,
            annotations=[dict(text="Waiting for telemetry…", showarrow=False)],
        )
        return fig

    fig = make_subplots(
        rows=len(metrics),
        cols=1,
        shared_xaxes=True,
        subplot_titles=[_METRIC_LABEL.get(m, m) for m in metrics],
        vertical_spacing=0.08,
    )

    for i, metric in enumerate(metrics, start=1):
        fig.add_trace(
            go.Scatter(
                x=df["tick"],
                y=df[metric],
                mode="lines",
                line=dict(color=_METRIC_COLOR.get(metric, "#5B8FF9"), width=2),
                showlegend=False,
            ),
            row=i,
            col=1,
        )

    window = df["tick"]
    for tick in fault_ticks:
        if window.min() <= tick <= window.max():
            fig.add_vline(x=tick, line_dash="dash", line_color="#FF3333", opacity=0.6)

    fig.update_layout(
        template="plotly_dark",
        height=130 * len(metrics) + 40,
        margin=dict(l=10, r=10, t=30, b=10),
        title=dict(text=f"Telemetry — {entity}", x=0.01, font=dict(size=14)),
    )
    return fig

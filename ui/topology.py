"""Plotly network topology visualization.

Renders the twin as an interactive node-link graph: nodes colored by health status,
edges colored by current utilization. Nodes and edge midpoints carry their entity id
as customdata so the app can resolve click selections.
"""

import plotly.graph_objects as go

from twin import faults
from twin.network import DEGRADED, DOWN, HEALTHY

STATUS_COLORS = {HEALTHY: "#00CC66", DEGRADED: "#FFAA00", DOWN: "#FF3333"}

# Visual treatment per node type.
_NODE_STYLE = {
    "ue_cluster": {"symbol": "circle", "size": 20},
    "base_station": {"symbol": "square", "size": 26},
    "edge_cloud": {"symbol": "diamond", "size": 28},
    "core_function": {"symbol": "star", "size": 30},
}

_GREEN = (0, 204, 102)
_YELLOW = (255, 170, 0)
_RED = (255, 51, 51)


def _blend(a: tuple, b: tuple, t: float) -> str:
    """Interpolate between two RGB tuples and return an rgb() string."""
    r, g, bl = (int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return f"rgb({r},{g},{bl})"


def _util_color(util: float) -> str:
    """Green -> yellow -> red gradient for an edge utilization percentage."""
    u = max(0.0, min(100.0, util))
    if u <= 50.0:
        return _blend(_GREEN, _YELLOW, u / 50.0)
    return _blend(_YELLOW, _RED, (u - 50.0) / 50.0)


def _node_hover(node: str, data: dict) -> str:
    return (
        f"<b>{node}</b> ({data['type']})<br>"
        f"status: {data['status']}<br>"
        f"cpu: {data.get('cpu_utilization', 0):.0f}%  "
        f"mem: {data.get('memory_utilization', 0):.0f}%"
    )


def build_topology_figure(graph, selected: str | None = None) -> go.Figure:
    """Build the topology figure, highlighting `selected` (a node or edge id)."""
    pos = {n: graph.nodes[n]["pos"] for n in graph.nodes}
    fig = go.Figure()

    # One line trace per edge so each can take its own utilization color.
    mid_x, mid_y, mid_color, mid_text, mid_custom = [], [], [], [], []
    for u, v, data in graph.edges(data=True):
        eid = faults.edge_id(u, v)
        util = data.get("utilization_current", data["utilization_baseline"])
        color = _util_color(util)
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        width = 6 if eid == selected else 2 + util / 40.0
        # Radio edges replay real TelecomTS traces (solid); the rest is synthetic (dashed).
        is_real = "traces" in data
        fig.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[y0, y1],
                mode="lines",
                line=dict(color=color, width=width, dash=None if is_real else "dash"),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        mid_x.append((x0 + x1) / 2)
        mid_y.append((y0 + y1) / 2)
        mid_color.append(color)
        source = "real 5G trace" if is_real else "synthetic"
        mid_text.append(f"<b>{eid}</b> ({source})<br>utilization: {util:.0f}%")
        mid_custom.append(eid)

    # Selectable, hoverable markers at edge midpoints.
    fig.add_trace(
        go.Scatter(
            x=mid_x,
            y=mid_y,
            mode="markers",
            marker=dict(size=10, color=mid_color, symbol="square", opacity=0.85),
            customdata=mid_custom,
            hovertext=mid_text,
            hoverinfo="text",
            showlegend=False,
        )
    )

    # Node markers.
    node_x, node_y, node_color, node_size, node_symbol = [], [], [], [], []
    node_text, node_label, node_line_w, node_custom = [], [], [], []
    for node, data in graph.nodes(data=True):
        x, y = pos[node]
        style = _NODE_STYLE[data["type"]]
        node_x.append(x)
        node_y.append(y)
        node_color.append(STATUS_COLORS[data["status"]])
        node_size.append(style["size"])
        node_symbol.append(style["symbol"])
        node_text.append(_node_hover(node, data))
        node_label.append(node)
        node_line_w.append(4 if node == selected else 1)
        node_custom.append(node)

    fig.add_trace(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers",
            marker=dict(
                color=node_color,
                size=node_size,
                symbol=node_symbol,
                line=dict(color="white", width=node_line_w),
            ),
            customdata=node_custom,
            hovertext=node_text,
            hoverinfo="text",
            showlegend=False,
        )
    )

    # Bold, dark labels on a light pill so they read clearly on the dark canvas.
    for label, x, y in zip(node_label, node_x, node_y):
        fig.add_annotation(
            x=x,
            y=y,
            text=f"<b>{label}</b>",
            showarrow=False,
            yshift=-24,
            yanchor="top",
            font=dict(size=13, color="#111111"),
            bgcolor="rgba(255,255,255,0.9)",
            borderpad=3,
        )

    # Legend entries explaining the line styles (real vs synthetic data).
    for label, dash in (("real 5G trace", None), ("synthetic", "dash")):
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                line=dict(color="#888888", width=3, dash=dash),
                name=label,
                showlegend=True,
            )
        )

    fig.update_layout(
        template="plotly_dark",
        showlegend=True,
        hoverlabel=dict(font=dict(size=15), namelength=-1),
        legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom", font=dict(size=11)),
        margin=dict(l=10, r=10, t=10, b=10),
        height=420,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        clickmode="event+select",
        dragmode=False,
    )
    return fig

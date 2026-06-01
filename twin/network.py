"""NetworkX digital twin of a small 6G-inspired network.

Builds a static topology of UE clusters, base stations, edge clouds, and 5G core
functions (AMF/SMF/UPF). Baselines are grounded in 3GPP-style targets: data-plane
links carry high throughput, control-plane links (N2/N4/N11) carry low-volume but
latency-critical signaling, and per-node CPU/memory/session loads reflect each
function's role (UPF is the busiest, every data packet flows through it).

Radio-access edges (UE <-> base station) replay real TelecomTS traces at runtime;
their synthetic baselines here are only fallbacks.
"""

import networkx as nx

# Node status values used across the twin and UI.
HEALTHY = "healthy"
DEGRADED = "degraded"
DOWN = "down"


def build_network() -> nx.Graph:
    """Build and return the 6G-inspired topology as a NetworkX graph."""
    g = nx.Graph()

    # (id, type, x, y, cpu%, mem%, active_sessions) — grounded per-node baselines.
    nodes = [
        ("UE1", "ue_cluster", 0, 2, 15, 20, 60),
        ("UE2", "ue_cluster", 0, 1, 15, 20, 60),
        ("UE3", "ue_cluster", 0, 0, 15, 20, 60),
        ("BS1", "base_station", 1, 2, 50, 60, 250),
        ("BS2", "base_station", 1, 1, 50, 60, 250),
        ("BS3", "base_station", 1, 0, 50, 60, 250),
        ("EDGE1", "edge_cloud", 2, 1.5, 40, 50, 300),
        ("EDGE2", "edge_cloud", 2, 0, 38, 48, 250),
        ("UPF", "core_function", 3, 1, 60, 50, 1500),   # busiest: all data sessions
        ("SMF", "core_function", 4, 1.5, 35, 45, 650),
        ("AMF", "core_function", 4, 0.5, 30, 40, 1200),
    ]
    for node_id, node_type, x, y, cpu, mem, sessions in nodes:
        g.add_node(
            node_id,
            type=node_type,
            status=HEALTHY,
            pos=(x, y),
            cpu_baseline=float(cpu),
            memory_baseline=float(mem),
            sessions_baseline=float(sessions),
            cpu_utilization=float(cpu),
            memory_utilization=float(mem),
        )

    # (u, v, plane, latency_ms, throughput_mbps, utilization%, packet_loss%).
    #   radio   : UE<->BS, replayed from real traces (these values are fallbacks)
    #   data    : high-throughput user-plane backhaul / N3
    #   control : low-volume but latency-critical signaling (N2/N4/N11)
    edges = [
        ("UE1", "BS1", "radio", 8.0, 100, 35, 1.0),
        ("UE2", "BS2", "radio", 8.0, 100, 40, 1.0),
        ("UE3", "BS3", "radio", 9.0, 100, 30, 1.0),
        ("BS1", "EDGE1", "data", 1.5, 5000, 45, 0.005),
        ("BS2", "EDGE1", "data", 1.5, 5000, 50, 0.005),
        ("BS3", "EDGE2", "data", 1.5, 5000, 35, 0.005),
        ("EDGE1", "UPF", "data", 3.0, 20000, 40, 0.005),
        ("EDGE2", "UPF", "data", 3.0, 20000, 30, 0.005),
        ("BS1", "AMF", "control", 1.5, 50, 15, 0.001),   # N2
        ("BS3", "AMF", "control", 1.5, 50, 15, 0.001),   # N2
        ("AMF", "SMF", "control", 0.8, 20, 10, 0.001),   # N11
        ("SMF", "UPF", "control", 0.8, 20, 10, 0.001),   # N4
    ]
    for u, v, plane, latency, throughput, utilization, loss in edges:
        g.add_edge(
            u,
            v,
            plane=plane,
            latency_baseline=float(latency),
            throughput_baseline=float(throughput),
            utilization_baseline=float(utilization),
            packet_loss_baseline=float(loss),
        )

    return g

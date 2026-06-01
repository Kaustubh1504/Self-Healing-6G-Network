"""Telemetry generation for the digital twin.

Radio-access edges replay real TelecomTS KPI traces (a `normal` trace, swapped for an
anomaly trace while a radio fault is active). Everything else is synthesised, but not
as plain independent Gaussian noise — telecom traffic is bursty and non-stationary, so
the model layers:

  * diurnal drift    — a slow sine modulating baselines (time-of-day load)
  * micro-bursts     — Poisson-triggered short spikes on data-plane links
  * Gaussian jitter  — a small ambient noise floor
  * correlated degradation — nodes are computed first, then synthetic-link latency and
    throughput couple to endpoint CPU, so load on a node propagates into its links
    (this is how fault cascades travel through the dependency graph).

Each entity keeps a rolling-window pandas DataFrame of its recent samples.
"""

import networkx as nx
import numpy as np
import pandas as pd

from twin import dataset, faults
from twin.network import DOWN, HEALTHY

WINDOW = 60  # ticks of history retained per entity

# Non-stationary model parameters.
DIURNAL_PERIOD = 240   # ticks per simulated "day"
DIURNAL_AMP = 0.12     # +/- baseline modulation
BURST_LAMBDA = 0.05    # per-tick probability of starting a micro-burst (data-plane)
CPU_REF = 65.0         # CPU above which a node starts stressing its links
LATENCY_PER_STRESS = 0.03    # latency multiplier added per CPU point over CPU_REF
THROUGHPUT_PER_STRESS = 0.006  # throughput fraction lost per CPU point over CPU_REF

# Relative Gaussian noise (fraction of baseline) for the ambient jitter floor.
_NOISE = {
    "cpu_pct": 0.04,
    "memory_pct": 0.03,
    "active_sessions": 0.05,
    "latency_ms": 0.05,
    "throughput_mbps": 0.04,
    "packet_loss_pct": 0.20,
    "utilization_pct": 0.04,
}

NODE_METRICS = ["cpu_pct", "memory_pct", "active_sessions", "status"]
EDGE_METRICS = ["latency_ms", "throughput_mbps", "packet_loss_pct", "utilization_pct"]


def _radio_key(u: str, v: str):
    """Lookup key into dataset.RADIO_TRACES for an edge, or None if not a radio edge."""
    key = tuple(sorted((u, v)))
    return key if key in dataset.RADIO_TRACES else None


def _noisy(baseline: float, metric: str) -> float:
    """Baseline plus Gaussian jitter scaled by the metric's relative noise level."""
    return baseline + np.random.normal(0.0, abs(baseline) * _NOISE[metric] + 1e-9)


def _diurnal(current_tick: int) -> float:
    """Slow time-of-day load multiplier."""
    return 1.0 + DIURNAL_AMP * np.sin(2.0 * np.pi * current_tick / DIURNAL_PERIOD)


def init_store(graph: nx.Graph) -> dict[str, pd.DataFrame]:
    """Create rolling-window DataFrames; preload real traces and burst state on edges."""
    store: dict[str, pd.DataFrame] = {}
    for node in graph.nodes:
        store[node] = pd.DataFrame(columns=["tick"] + NODE_METRICS)
    for u, v in graph.edges:
        eid = faults.edge_id(u, v)
        key = _radio_key(u, v)
        if key is not None:
            graph.edges[u, v]["traces"] = {
                name: dataset.load_trace(tk) for name, tk in dataset.RADIO_TRACES[key].items()
            }
            store[eid] = pd.DataFrame(columns=["tick"] + dataset.RADIO_COLUMNS)
        else:
            graph.edges[u, v]["burst_remaining"] = 0
            graph.edges[u, v]["burst_mult"] = 1.0
            store[eid] = pd.DataFrame(columns=["tick"] + EDGE_METRICS)
    return store


def _node_record(data: dict, status: str, load: dict, diurnal: float) -> dict:
    """One tick of synthesised node telemetry, with diurnal drift and fault loads."""
    if status == DOWN:  # a downed function processes nothing
        return {"cpu_pct": 0.0, "memory_pct": 0.0, "active_sessions": 0, "status": status}
    cpu_center = load["cpu"] if "cpu" in load else data["cpu_baseline"] * diurnal
    mem_center = load["mem"] if "mem" in load else data["memory_baseline"] * diurnal
    sess_center = data["sessions_baseline"] * diurnal * load.get("sessions_mult", 1.0)
    return {
        "cpu_pct": float(np.clip(_noisy(cpu_center, "cpu_pct"), 0.0, 100.0)),
        "memory_pct": float(np.clip(_noisy(mem_center, "memory_pct"), 0.0, 100.0)),
        "active_sessions": int(max(0.0, _noisy(sess_center, "active_sessions"))),
        "status": status,
    }


def _micro_burst(data: dict) -> float:
    """Poisson-triggered short traffic spike multiplier for a data-plane link."""
    remaining = data.get("burst_remaining", 0)
    if remaining <= 0 and np.random.random() < BURST_LAMBDA:
        remaining = int(np.random.randint(1, 4))  # 1-3 ticks
        data["burst_mult"] = float(np.random.uniform(2.0, 3.0))
    if remaining > 0:
        data["burst_remaining"] = remaining - 1
        return data["burst_mult"]
    data["burst_remaining"] = 0
    return 1.0


def _synthetic_edge_record(data: dict, mult: dict, max_cpu: float, diurnal: float) -> dict:
    """One tick of synthesised edge telemetry: drift + bursts + CPU coupling + faults."""
    burst = _micro_burst(data) if data["plane"] == "data" else 1.0
    load_mult = diurnal * burst
    cpu_stress = max(0.0, max_cpu - CPU_REF)  # endpoint load bleeding into the link

    utilization = _noisy(data["utilization_baseline"] * load_mult, "utilization_pct")
    utilization *= mult.get("utilization_pct", 1.0)
    utilization = float(np.clip(utilization, 0.0, 100.0))

    throughput = data["throughput_baseline"] * load_mult
    throughput *= max(0.3, 1.0 - THROUGHPUT_PER_STRESS * cpu_stress)
    throughput = _noisy(throughput, "throughput_mbps") * mult.get("throughput_mbps", 1.0)

    latency = data["latency_baseline"] * (1.0 + LATENCY_PER_STRESS * cpu_stress)
    latency = _noisy(latency, "latency_ms") * mult.get("latency_ms", 1.0)

    loss = data["packet_loss_baseline"]
    if utilization > 90.0:  # congested links start dropping packets
        loss += (utilization - 90.0) * 0.5
    loss = _noisy(loss, "packet_loss_pct") * mult.get("packet_loss_pct", 1.0)

    return {
        "latency_ms": float(max(0.0, latency)),
        "throughput_mbps": float(max(0.0, throughput)),
        "packet_loss_pct": float(max(0.0, loss)),
        "utilization_pct": utilization,
    }


def _radio_record(data: dict, source: str, current_tick: int) -> dict:
    """One tick replayed from a real trace (the active `source`, looping over the file)."""
    traces = data["traces"]
    df = traces.get(source, traces["normal"])
    row = df.iloc[current_tick % len(df)]
    return {col: float(row[col]) for col in dataset.RADIO_COLUMNS}


def _append(store: dict, entity: str, current_tick: int, record: dict, window: int) -> None:
    """Append a record to an entity's DataFrame, trimming to the rolling window."""
    record = {"tick": current_tick, **record}
    df = pd.concat([store[entity], pd.DataFrame([record])], ignore_index=True)
    store[entity] = df.tail(window).reset_index(drop=True)


def tick(
    graph: nx.Graph,
    store: dict[str, pd.DataFrame],
    current_tick: int,
    active_faults: list,
    window: int = WINDOW,
) -> None:
    """Advance the twin one tick: nodes first (so links can couple to their CPU)."""
    node_status, node_load, edge_mult, edge_source = faults.aggregate_overrides(
        active_faults, current_tick
    )
    diurnal = _diurnal(current_tick)

    for node, data in graph.nodes(data=True):
        status = node_status.get(node, HEALTHY)
        data["status"] = status
        record = _node_record(data, status, node_load.get(node, {}), diurnal)
        data["cpu_utilization"] = record["cpu_pct"]
        data["memory_utilization"] = record["memory_pct"]
        _append(store, node, current_tick, record, window)

    for u, v, data in graph.edges(data=True):
        eid = faults.edge_id(u, v)
        if "traces" in data:
            record = _radio_record(data, edge_source.get(eid, "normal"), current_tick)
        else:
            max_cpu = max(graph.nodes[u]["cpu_utilization"], graph.nodes[v]["cpu_utilization"])
            record = _synthetic_edge_record(data, edge_mult.get(eid, {}), max_cpu, diurnal)
        data["utilization_current"] = record["utilization_pct"]
        _append(store, eid, current_tick, record, window)

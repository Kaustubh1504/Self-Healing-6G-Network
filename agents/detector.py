"""Detector agent — rule-based anomaly detection on the telemetry store.

Deterministic by design (no LLM): detection thresholds are fixed, so an LLM here would
only add latency and cost. It reads the latest sample of every entity from the rolling
window and flags threshold violations. The reliable anchor across all fault scenarios is
the node `status` flip (DEGRADED/DOWN); metric violations add the specificity the
knowledge graph matches on. LLM reasoning begins downstream at Diagnosis.

Output: {"anomaly_detected": bool, "violations": [...], "tick": int}
    violation: {"entity", "metric", "value", "threshold"}
"""

import pandas as pd

from twin import faults
from twin.network import DEGRADED, DOWN

# Absolute thresholds. (metric, comparison, threshold) — comparison is "gt" or "lt".
_NODE_RULES = [("cpu_pct", "gt", 90.0), ("memory_pct", "gt", 85.0)]
_RADIO_RULES = [("packet_loss_pct", "gt", 5.0), ("snr_db", "lt", 15.0), ("utilization_pct", "gt", 80.0)]
_SYNTH_RULES = [("utilization_pct", "gt", 90.0), ("packet_loss_pct", "gt", 2.0)]

_LATENCY_BASELINE_MULT = 3.0   # synthetic-edge latency flagged above 3x its baseline
_THROUGHPUT_DROP_PCT = 40.0    # gradual throughput decay over the lookback window
_DROP_LOOKBACK = 20            # ticks back to compare throughput against


def _violated(value: float, comparison: str, threshold: float) -> bool:
    return value > threshold if comparison == "gt" else value < threshold


def run(graph, store: dict[str, pd.DataFrame], tick: int) -> dict:
    """Scan the latest telemetry sample of every entity and flag threshold violations."""
    violations: list[dict] = []

    # Primary nodes carry the operational-state alarm (status / compute breach). These
    # are deterministic fault signals — unlike the real radio traces, whose normal BLER
    # and bursty throughput would otherwise trip the radio rules constantly. An anomaly
    # is only declared when a node enters such a state; radio/cascade KPI violations are
    # collected as corroborating evidence, scoped to the fault's locus.
    primary_nodes: set[str] = set()
    for node, data in graph.nodes(data=True):
        df = store.get(node)
        if df is None or df.empty:
            continue
        row = df.iloc[-1]
        if row.get("status") in (DEGRADED, DOWN):
            violations.append({"entity": node, "metric": "status", "value": row["status"], "threshold": "healthy"})
            primary_nodes.add(node)
        for metric, comparison, threshold in _NODE_RULES:
            if _violated(float(row[metric]), comparison, threshold):
                violations.append({"entity": node, "metric": metric, "value": round(float(row[metric]), 1), "threshold": threshold})
                primary_nodes.add(node)

    if not primary_nodes:
        return {"anomaly_detected": False, "violations": [], "tick": tick}

    for u, v, data in graph.edges(data=True):
        # Scope edge evidence to links incident to a primary node (the fault's locus).
        if u not in primary_nodes and v not in primary_nodes:
            continue
        eid = faults.edge_id(u, v)
        df = store.get(eid)
        if df is None or df.empty:
            continue
        row = df.iloc[-1]
        is_radio = "traces" in data
        rules = _RADIO_RULES if is_radio else _SYNTH_RULES
        for metric, comparison, threshold in rules:
            if metric in row and _violated(float(row[metric]), comparison, threshold):
                violations.append({"entity": eid, "metric": metric, "value": round(float(row[metric]), 2), "threshold": threshold})

        # Synthetic-edge latency relative to its own baseline (cascade signal).
        if not is_radio and "latency_ms" in row:
            limit = data["latency_baseline"] * _LATENCY_BASELINE_MULT
            if float(row["latency_ms"]) > limit:
                violations.append({"entity": eid, "metric": "latency_ms", "value": round(float(row["latency_ms"]), 2), "threshold": round(limit, 2)})

        # Gradual throughput decay (SLA-breach signal): compare against the lookback sample.
        if "throughput_mbps" in row and len(df) > _DROP_LOOKBACK:
            past = float(df["throughput_mbps"].iloc[-1 - _DROP_LOOKBACK])
            now = float(row["throughput_mbps"])
            if past > 0:
                drop_pct = (past - now) / past * 100.0
                if drop_pct > _THROUGHPUT_DROP_PCT:
                    violations.append({"entity": eid, "metric": "throughput_drop_pct", "value": round(drop_pct, 1), "threshold": _THROUGHPUT_DROP_PCT})

    return {"anomaly_detected": True, "violations": violations, "tick": tick}


def violations_to_metrics(violations: list[dict]) -> dict:
    """Flatten violations to the {'entity.metric': value} dict the KG lookup consumes."""
    return {f"{v['entity']}.{v['metric']}": v["value"] for v in violations}

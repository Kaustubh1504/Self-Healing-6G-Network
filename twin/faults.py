"""Fault injection for the digital twin.

Faults express a primary effect plus cascade effects that propagate through the
dependency graph — the propagation a Diagnosis agent would have to untangle.

  * Radio faults (Congestion, Jammer) swap a radio edge to a real TelecomTS anomaly
    trace AND push a CPU load onto the connected base station. The base-station load
    then cascades through the synthetic backhaul via the CPU->link coupling in
    telemetry (the real trace itself is never overwritten).
  * Node Overload drives a node's CPU/memory up and rejects sessions; the elevated
    CPU cascades into its synthetic links.
  * Service Down takes a core function down and degrades its signaling links and
    dependent functions (SMF down -> no new sessions via UPF).
  * SLA Breach is a slow burn: throughput on a data path decays gradually, latency
    creeping up with no sudden spike.

Each tick the active faults are collapsed into override maps telemetry applies.
"""

from dataclasses import dataclass, field

import networkx as nx

from twin.network import DEGRADED, DOWN


def edge_id(u: str, v: str) -> str:
    """Canonical, order-independent id for the edge between two nodes."""
    return "-".join(sorted((u, v)))


@dataclass
class Fault:
    """An active fault: a primary effect plus cascades, for a fixed number of ticks."""

    name: str
    label: str
    duration_ticks: int
    start_tick: int
    status_node: str          # node whose status changes while active
    status: str               # DEGRADED or DOWN
    source: str | None = None       # radio: anomaly trace to replay
    edge_target: str | None = None  # radio: edge id to swap
    load: dict = field(default_factory=dict)        # node_id -> {cpu, mem, sessions_mult}
    edge_effect: dict = field(default_factory=dict)  # edge_id -> {metric: multiplier}
    gradual_edge: dict = field(default_factory=dict)  # edge_id -> {metric: target multiplier}


_N2_SMF = edge_id("AMF", "SMF")
_N4 = edge_id("SMF", "UPF")

_SCENARIOS = {
    "congestion": dict(
        label="Network Congestion",
        duration_ticks=30,
        status_node="BS2",
        status=DEGRADED,
        source="congestion",
        edge_target=edge_id("BS2", "UE2"),
        load={"BS2": {"cpu": 85, "mem": 75}},  # cascades into BS2<->EDGE1 backhaul
    ),
    "jammer": dict(
        label="RF Jammer",
        duration_ticks=30,
        status_node="BS1",
        status=DEGRADED,
        source="jammer",
        edge_target=edge_id("BS1", "UE1"),
        load={"BS1": {"cpu": 80, "mem": 72}},  # cascades into BS1 backhaul + N2
    ),
    "node_overload": dict(
        label="Node Overload (BS3)",
        duration_ticks=25,
        status_node="BS3",
        status=DEGRADED,
        load={"BS3": {"cpu": 96, "mem": 88, "sessions_mult": 0.6}},  # rejects sessions
    ),
    "service_down": dict(
        label="Service Down (SMF)",
        duration_ticks=25,
        status_node="SMF",
        status=DOWN,
        edge_effect={
            _N2_SMF: {"latency_ms": 3.0, "throughput_mbps": 0.3, "packet_loss_pct": 15.0},
            _N4: {"latency_ms": 3.0, "throughput_mbps": 0.3, "packet_loss_pct": 15.0},
        },
        load={"UPF": {"sessions_mult": 0.3}},  # no new sessions via UPF
    ),
    "sla_breach": dict(
        label="SLA Breach (EDGE1-UPF)",
        duration_ticks=40,
        status_node="EDGE1",
        status=DEGRADED,
        gradual_edge={edge_id("EDGE1", "UPF"): {"throughput_mbps": 0.45, "latency_ms": 1.6}},
    ),
}

SCENARIO_NAMES = list(_SCENARIOS)


def scenario_label(name: str) -> str:
    """Human-readable label for a scenario name."""
    return _SCENARIOS[name]["label"]


def make_fault(name: str, start_tick: int) -> Fault:
    """Construct an active Fault for the given scenario, starting at `start_tick`."""
    return Fault(name=name, start_tick=start_tick, **_SCENARIOS[name])


def is_expired(fault: Fault, current_tick: int) -> bool:
    """True once the fault has run for its full duration."""
    return current_tick - fault.start_tick >= fault.duration_ticks


def _merge_mult(target: dict, overrides: dict) -> None:
    """Multiply `overrides` into `target` so stacked faults compound."""
    for metric, mult in overrides.items():
        target[metric] = target.get(metric, 1.0) * mult


def aggregate_overrides(active_faults: list[Fault], current_tick: int):
    """Collapse active faults into override maps for the current tick.

    Returns (node_status, node_load, edge_mult, edge_source):
      node_status: node_id -> imposed status
      node_load:   node_id -> {cpu, mem, sessions_mult}   (primary + cascade loads)
      edge_mult:   edge_id -> {metric: multiplier}         (static + gradual effects)
      edge_source: edge_id -> anomaly trace name           (radio faults)
    """
    node_status: dict[str, str] = {}
    node_load: dict[str, dict] = {}
    edge_mult: dict[str, dict] = {}
    edge_source: dict[str, str] = {}

    for fault in active_faults:
        node_status[fault.status_node] = fault.status
        if fault.source:
            edge_source[fault.edge_target] = fault.source
        for node, vals in fault.load.items():
            node_load.setdefault(node, {}).update(vals)
        for eid, eff in fault.edge_effect.items():
            _merge_mult(edge_mult.setdefault(eid, {}), eff)
        if fault.gradual_edge:
            progress = min(1.0, (current_tick - fault.start_tick + 1) / fault.duration_ticks)
            for eid, targets in fault.gradual_edge.items():
                ramped = {m: 1.0 + (t - 1.0) * progress for m, t in targets.items()}
                _merge_mult(edge_mult.setdefault(eid, {}), ramped)

    return node_status, node_load, edge_mult, edge_source

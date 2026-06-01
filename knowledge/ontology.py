"""Telecom knowledge graph as RDF triples (RDFLib).

Encodes the diagnostic knowledge a human network engineer would carry: which alarm
signatures indicate which root cause, what remediates each cause, and which network
entities each cause/remediation touches. The Diagnosis agent queries this graph
(via SPARQL in knowledge.queries) instead of having the rules hard-coded in Python.

Ontology namespace: http://6g-twin/ontology/  (prefix TEL)

Triple shape (one group per fault scenario):

    AlarmPattern --TEL:indicates--> RootCause
    AlarmPattern --TEL:hasCondition--> Condition
        Condition --TEL:metric--> "snr_db"
        Condition --TEL:operator--> "lt"
        Condition --TEL:threshold--> "15.0"
    RootCause   --TEL:resolvedBy--> Remediation
    RootCause   --TEL:affects-->    NetworkEntity
    Remediation --TEL:targets-->    NetworkEntity

Conditions are reified (a condition node per metric) so one alarm pattern can carry
several metric thresholds — the flat AlarmPattern->metric/threshold edges in the
design note only allow one metric each.
"""

from rdflib import Graph, Literal, Namespace, RDFS
from rdflib.extras.external_graph_libs import rdflib_to_networkx_digraph
import networkx as nx

TEL = Namespace("http://6g-twin/ontology/")

# (alarm pattern, root cause, remediation, human label, conditions, affected entities)
#   condition: (metric, operator, threshold)  operators: gt | lt | eq
#   affected entities double as the localisation signal the Diagnosis match scores on.
_KNOWLEDGE = [
    {
        "pattern": "pattern_rf_interference",
        "root_cause": "rf_interference",
        "remediation": "isolate_frequency_band",
        "label": "RF Interference",
        "remediation_label": "Isolate frequency band",
        "conditions": [
            ("snr_db", "lt", 15.0),
            ("packet_loss_pct", "gt", 5.0),
            ("status", "eq", "degraded"),
        ],
        "affects": ["BS1", "BS1-UE1"],
    },
    {
        "pattern": "pattern_radio_congestion",
        "root_cause": "radio_congestion",
        "remediation": "offload_traffic",
        "label": "Radio Congestion",
        "remediation_label": "Offload traffic",
        "conditions": [
            ("utilization_pct", "gt", 80.0),
            ("throughput_drop_pct", "gt", 50.0),
            ("status", "eq", "degraded"),
        ],
        "affects": ["BS2", "BS2-UE2"],
    },
    {
        "pattern": "pattern_compute_overload",
        "root_cause": "compute_overload",
        "remediation": "offload_to_edge_cloud",
        "label": "Compute Overload",
        "remediation_label": "Offload to edge cloud",
        "conditions": [
            ("cpu_pct", "gt", 90.0),
            ("memory_pct", "gt", 85.0),
            ("status", "eq", "degraded"),
        ],
        "affects": ["BS3", "BS3-EDGE2"],
    },
    {
        "pattern": "pattern_core_function_crash",
        "root_cause": "core_function_crash",
        "remediation": "restart_network_function",
        "label": "Core Function Crash",
        "remediation_label": "Restart network function",
        "conditions": [
            ("status", "eq", "down"),
            ("latency_ms", "gt", 0.0),
        ],
        "affects": ["SMF", "AMF-SMF", "SMF-UPF", "UPF"],
    },
    {
        "pattern": "pattern_path_degradation",
        "root_cause": "path_degradation",
        "remediation": "reroute_traffic",
        "label": "Path Degradation",
        "remediation_label": "Reroute traffic",
        "conditions": [
            ("throughput_drop_pct", "gt", 40.0),
            ("status", "eq", "degraded"),
        ],
        "affects": ["EDGE1", "EDGE1-UPF"],
    },
]


def build_kg() -> Graph:
    """Construct and return the populated RDF knowledge graph."""
    g = Graph()
    g.bind("TEL", TEL)
    for entry in _KNOWLEDGE:
        pattern = TEL[entry["pattern"]]
        cause = TEL[entry["root_cause"]]
        remediation = TEL[entry["remediation"]]

        g.add((pattern, TEL.indicates, cause))
        g.add((pattern, RDFS.label, Literal(entry["label"])))
        g.add((cause, TEL.resolvedBy, remediation))
        g.add((cause, RDFS.label, Literal(entry["label"])))
        g.add((remediation, RDFS.label, Literal(entry["remediation_label"])))

        for i, (metric, operator, threshold) in enumerate(entry["conditions"]):
            cond = TEL[f"{entry['pattern']}_cond{i}"]
            g.add((pattern, TEL.hasCondition, cond))
            g.add((cond, TEL.metric, Literal(metric)))
            g.add((cond, TEL.operator, Literal(operator)))
            g.add((cond, TEL.threshold, Literal(str(threshold))))

        for entity in entry["affects"]:
            ent = TEL[entity]
            g.add((cause, TEL.affects, ent))
            g.add((remediation, TEL.targets, ent))
    return g


def get_kg_networkx(kg: Graph) -> nx.DiGraph:
    """Convert the RDF graph to a NetworkX DiGraph for visualization."""
    return rdflib_to_networkx_digraph(kg)

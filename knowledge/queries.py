"""SPARQL lookups over the telecom knowledge graph.

`find_root_cause` matches the Detector's observed metric violations against the KG's
alarm patterns; `find_remediation` looks up the fix for a diagnosed cause. Both return
plain Python dicts — the agents never touch raw SPARQL results.

Matching is two-signal: a pattern scores on (a) how many of its metric-threshold
conditions the observed violations satisfy and (b) how many of its affected entities
appear among the violating entities. Entity overlap localises the fault (BS1 vs BS2 vs
BS3 all look alike on metrics alone); the metric conditions add specificity. Confidence
blends the two fractions.
"""

from rdflib import Graph

from knowledge.ontology import TEL

_PATTERNS_QUERY = """
PREFIX TEL: <http://6g-twin/ontology/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?pattern ?label ?cause ?remediation ?metric ?operator ?threshold
WHERE {
    ?pattern TEL:indicates ?cause ;
             rdfs:label ?label ;
             TEL:hasCondition ?cond .
    ?cause TEL:resolvedBy ?remediation .
    ?cond TEL:metric ?metric ;
          TEL:operator ?operator ;
          TEL:threshold ?threshold .
}
"""

_AFFECTS_QUERY = """
PREFIX TEL: <http://6g-twin/ontology/>
SELECT ?entity WHERE { TEL:%s TEL:affects ?entity . }
"""

_REMEDIATION_QUERY = """
PREFIX TEL: <http://6g-twin/ontology/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?remediation ?label ?entity
WHERE {
    TEL:%s TEL:resolvedBy ?remediation .
    ?remediation rdfs:label ?label .
    OPTIONAL { ?remediation TEL:targets ?entity . }
}
"""


def _local(uri) -> str:
    """Strip the namespace, leaving the local id (e.g. 'rf_interference')."""
    return str(uri).split("/")[-1]


def _satisfied(value, operator: str, threshold: str) -> bool:
    """True if `value` violates the condition `operator threshold`."""
    if operator == "eq":
        return str(value).lower() == threshold.lower()
    try:
        v, t = float(value), float(threshold)
    except (TypeError, ValueError):
        return False
    return v > t if operator == "gt" else v < t


def find_root_cause(kg: Graph, alarm_metrics: dict) -> dict:
    """Match observed violations against KG alarm patterns; return the best root cause.

    `alarm_metrics`: {"entity.metric": value}, e.g. {"BS1.status": "degraded",
    "BS1-UE1.snr_db": 12.1}. Returns {root_cause, confidence, affected_entities, evidence}.
    """
    violating_entities = {key.split(".", 1)[0] for key in alarm_metrics}

    # Gather each pattern's conditions and metadata from the KG.
    patterns: dict[str, dict] = {}
    for row in kg.query(_PATTERNS_QUERY):
        pid = _local(row.pattern)
        p = patterns.setdefault(
            pid,
            {
                "label": str(row.label),
                "cause": _local(row.cause),
                "remediation": _local(row.remediation),
                "conditions": [],
            },
        )
        p["conditions"].append((str(row.metric), str(row.operator), str(row.threshold)))

    best = None
    for pid, p in patterns.items():
        affected = [_local(r.entity) for r in kg.query(_AFFECTS_QUERY % p["cause"])]
        entity_hits = sum(1 for e in affected if e in violating_entities)
        if entity_hits == 0:
            continue  # wrong locality — this pattern is not what fired

        # A node going DEGRADED/DOWN is the authoritative, noise-proof localizer: transient
        # KPI spikes never flip status, so status hits dominate ranking over metric noise.
        status_hits = sum(
            1 for e in affected
            if str(alarm_metrics.get(f"{e}.status", "")).lower() in ("degraded", "down")
        )

        evidence = []
        metric_hits = 0
        for metric, operator, threshold in p["conditions"]:
            for key, value in alarm_metrics.items():
                if key.split(".", 1)[1] == metric and _satisfied(value, operator, threshold):
                    metric_hits += 1
                    evidence.append(f"{key} = {value} satisfies {metric} {operator} {threshold}")
                    break

        entity_frac = entity_hits / len(affected)
        metric_frac = metric_hits / len(p["conditions"]) if p["conditions"] else 0.0
        confidence = round(0.55 + 0.45 * (0.6 * entity_frac + 0.4 * metric_frac), 2)
        evidence.insert(
            0,
            f"KG pattern '{p['label']}' matched on entities "
            f"{[e for e in affected if e in violating_entities]}",
        )

        score = (status_hits, metric_hits, entity_hits)
        if best is None or score > best["_score"]:
            best = {
                "root_cause": p["cause"],
                "confidence": confidence,
                "affected_entities": affected,
                "evidence": evidence,
                "_score": score,
            }

    if best is None:
        return {"root_cause": None, "confidence": 0.0, "affected_entities": [], "evidence": []}
    best.pop("_score")
    return best


_PATH_QUERY = """
PREFIX TEL: <http://6g-twin/ontology/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?pattern ?patternLabel ?remediation ?remediationLabel
WHERE {
    ?pattern TEL:indicates TEL:%s ; rdfs:label ?patternLabel .
    TEL:%s TEL:resolvedBy ?remediation .
    ?remediation rdfs:label ?remediationLabel .
}
"""


def kg_path(kg: Graph, root_cause: str) -> dict:
    """The matched [AlarmPattern -> RootCause -> Remediation] chain, for visualization."""
    rows = list(kg.query(_PATH_QUERY % (root_cause, root_cause)))
    if not rows:
        return {}
    r = rows[0]
    affected = [_local(x.entity) for x in kg.query(_AFFECTS_QUERY % root_cause)]
    return {
        "alarm_pattern": str(r.patternLabel),
        "root_cause": root_cause,
        "remediation": _local(r.remediation),
        "remediation_label": str(r.remediationLabel),
        "affected_entities": affected,
    }


def find_remediation(kg: Graph, root_cause: str) -> dict:
    """Look up the remediation for a root cause. Returns {action, target_entities, description}."""
    action = None
    label = None
    targets = []
    for row in kg.query(_REMEDIATION_QUERY % root_cause):
        action = _local(row.remediation)
        label = str(row.label)
        if row.entity is not None:
            targets.append(_local(row.entity))
    return {"action": action, "target_entities": targets, "description": label}

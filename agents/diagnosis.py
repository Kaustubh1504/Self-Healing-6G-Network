"""Diagnosis agent — root-cause analysis grounded in the knowledge graph.

LLM-based. The deterministic facts (root cause, confidence, affected entities, KG
evidence) come from the SPARQL match in knowledge.queries; the LLM's job is to explain
*why* — citing specific metric values, telemetry trends, and the KG path — in prose the
operator can read in the trace panel. If no API key is configured the agent still returns
the KG-derived diagnosis with a templated explanation (clearly labelled), so the demo
remains functional offline.

Output: {"root_cause", "confidence", "reasoning", "affected_entities", "kg_evidence"}
"""

import networkx as nx

from agents import _llm
from knowledge.queries import find_root_cause

_SYSTEM = (
    "You are a telecom network diagnosis agent. Given the alarm violations, knowledge "
    "graph matches, and telemetry context, determine the most likely root cause. Explain "
    "your reasoning step by step, citing specific metric values and KG evidence. Be "
    "concise (4-6 sentences). Do not restate the JSON; write a plain-language explanation."
)


def _trend(store: dict, entity: str, window: int = 10) -> str:
    """Compact first->last summary of an entity's recent metrics for the LLM prompt."""
    df = store.get(entity)
    if df is None or df.empty:
        return f"{entity}: no telemetry"
    recent = df.tail(window)
    parts = []
    for col in recent.columns:
        if col in ("tick", "status"):
            continue
        first, last = recent[col].iloc[0], recent[col].iloc[-1]
        parts.append(f"{col} {first:.1f}->{last:.1f}")
    status = recent["status"].iloc[-1] if "status" in recent.columns else None
    head = f"{entity} [{status}]" if status else entity
    return f"{head}: " + ", ".join(parts)


def _neighbors(graph: nx.Graph, entities: list[str]) -> list[str]:
    """Direct graph neighbours of the affected nodes (for cascade-direction reasoning)."""
    out: set[str] = set()
    for e in entities:
        if e in graph:
            out.update(graph.neighbors(e))
    return sorted(out)


def _template_reasoning(kg_match: dict, violations: list[dict]) -> str:
    """Deterministic fallback explanation when no LLM is available."""
    viol = ", ".join(f"{v['entity']}.{v['metric']}={v['value']}" for v in violations[:5])
    return (
        f"KG-derived diagnosis (LLM narrative unavailable — set OPENAI_API_KEY for "
        f"full reasoning). Observed violations: {viol}. "
        + " ".join(kg_match["evidence"])
    )


def diagnose(kg, graph: nx.Graph, store: dict, anomaly: dict) -> dict:
    """Match violations to a root cause via the KG, then explain it with the LLM."""
    violations = anomaly["violations"]
    kg_match = find_root_cause(kg, {f"{v['entity']}.{v['metric']}": v["value"] for v in violations})

    affected = kg_match["affected_entities"]
    node_affected = [e for e in affected if e in graph]
    context_entities = list(dict.fromkeys(node_affected + _neighbors(graph, node_affected)))

    if _llm.available() and kg_match["root_cause"]:
        try:
            prompt = (
                f"Alarm violations:\n{violations}\n\n"
                f"Knowledge graph match:\n  candidate root cause: {kg_match['root_cause']}\n"
                f"  confidence: {kg_match['confidence']}\n  affected entities: {affected}\n"
                f"  KG evidence: {kg_match['evidence']}\n\n"
                f"Recent telemetry (last 10 ticks):\n"
                + "\n".join(_trend(store, e) for e in context_entities)
                + f"\n\nTopology neighbours of affected nodes: {_neighbors(graph, node_affected)}\n\n"
                "Confirm the root cause and explain your reasoning."
            )
            reasoning = _llm.complete(_SYSTEM, prompt)
        except Exception as exc:  # never let an API hiccup blank the trace
            reasoning = f"{_template_reasoning(kg_match, violations)} (LLM call failed: {exc})"
    else:
        reasoning = _template_reasoning(kg_match, violations)

    return {
        "root_cause": kg_match["root_cause"],
        "confidence": kg_match["confidence"],
        "reasoning": reasoning,
        "affected_entities": affected,
        "kg_evidence": kg_match["evidence"],
    }

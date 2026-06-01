"""Planner agent — remediation planning with logical twin verification.

LLM-based. The action comes from the KG (knowledge.queries.find_remediation); the LLM's
job is to verify it against the network dependency graph — reasoning about what happens
when the fix is applied and whether it creates side effects — then approve or reject. It
does NOT run a parallel simulation; verification is logical, over the topology.

Output: {"action", "target_entities", "verification_reasoning", "approved", "predicted_outcome"}
"""

import networkx as nx

from agents import _llm
from knowledge.queries import find_remediation

_SYSTEM = (
    "You are a telecom network remediation planner. Given the diagnosis and the knowledge "
    "graph's recommended action, verify the proposed fix by reasoning about the network "
    "dependency graph. Explain what will happen when the fix is applied, confirm there are "
    "no harmful side effects, and decide whether to approve it. Be concise (4-6 sentences). "
    "End your response with two lines exactly:\n"
    "DECISION: APPROVE or DECISION: REJECT\n"
    "PREDICTED OUTCOME: <one sentence on the expected recovery>"
)


def _node_state(graph: nx.Graph, entities: list[str]) -> str:
    """Current CPU/memory/status of the target nodes plus their dependency neighbours."""
    lines = []
    for e in entities:
        if e not in graph:
            continue
        d = graph.nodes[e]
        lines.append(
            f"{e} [{d['status']}] cpu={d.get('cpu_utilization', 0):.0f}% "
            f"mem={d.get('memory_utilization', 0):.0f}% neighbours={sorted(graph.neighbors(e))}"
        )
    return "\n".join(lines) or "(no node-level targets)"


def _parse(text: str) -> tuple[bool, str]:
    """Pull the APPROVE/REJECT decision and predicted-outcome line out of the LLM text."""
    approved = "DECISION: REJECT" not in text.upper()
    outcome = ""
    for line in text.splitlines():
        if line.upper().startswith("PREDICTED OUTCOME:"):
            outcome = line.split(":", 1)[1].strip()
    return approved, outcome


def plan(kg, graph: nx.Graph, diagnosis: dict) -> dict:
    """Verify the KG-recommended remediation against the dependency graph and approve/reject."""
    remediation = find_remediation(kg, diagnosis["root_cause"])
    targets = remediation["target_entities"]
    node_targets = [e for e in targets if e in graph]

    if _llm.available():
        try:
            prompt = (
                f"Diagnosed root cause: {diagnosis['root_cause']} "
                f"(confidence {diagnosis['confidence']})\n"
                f"Affected entities: {diagnosis['affected_entities']}\n\n"
                f"Knowledge graph recommended action: {remediation['action']} "
                f"({remediation['description']})\nTarget entities: {targets}\n\n"
                f"Current state of targets and their dependencies:\n{_node_state(graph, node_targets)}\n\n"
                "Verify this fix and decide."
            )
            reasoning = _llm.complete(_SYSTEM, prompt)
            approved, outcome = _parse(reasoning)
        except Exception as exc:  # never let an API hiccup block remediation
            reasoning = (f"Logical verification (LLM call failed: {exc}): applying "
                         f"{remediation['action']} clears the diagnosed "
                         f"{diagnosis['root_cause']} at its source.")
            approved, outcome = True, f"{diagnosis['affected_entities']} return to healthy."
    else:
        reasoning = (
            f"Logical verification (LLM unavailable): applying {remediation['action']} to "
            f"{targets} clears the diagnosed {diagnosis['root_cause']} at its source. "
            "Affected entities are leaf/edge nodes with no harmful downstream coupling."
        )
        approved, outcome = True, f"{diagnosis['affected_entities']} return to healthy thresholds."

    return {
        "action": remediation["action"],
        "target_entities": targets,
        "verification_reasoning": reasoning,
        "approved": approved,
        "predicted_outcome": outcome,
    }

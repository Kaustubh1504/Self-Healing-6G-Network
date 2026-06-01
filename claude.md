# CLAUDE.md

## Project: Self-Healing 6G Network — Proof of Concept

A proof-of-concept of the multi-agent self-healing architecture proposed in Wu et al. (KDD 2026), "Towards Resilient and Autonomous Networks: A BlueSky Vision on AI-Native 6G." Demonstrates the autonomous detect → diagnose → recover loop from Section 3, grounded by the two infrastructure components from Section 3.3: a network digital twin and a telecommunications knowledge graph.

**Paper reference:** https://arxiv.org/abs/2605.21395
**Nokia KG reference:** https://www.nokia.com/blog/knowledge-graphs-the-lifeline-for-resilient-autonomous-networks/

---

## Behavioral Guidelines

Reduce common LLM coding mistakes. Bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

These guidelines are working if: fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Architecture Decisions (Locked)

These decisions are made. Do not revisit or suggest alternatives unless asked.

| Decision | Choice | Rationale |
|---|---|---|
| Digital twin engine | NetworkX (Python) | Lightweight, runs anywhere, focus is on agent logic not simulation fidelity |
| Telemetry data | Real 5G traces from TelecomTS (arXiv:2510.06063) for radio edges, synthetic for core | Dataset cited in the Nokia paper itself (reference [12]) |
| UI framework | Streamlit | Matches BubbleRAN ecosystem, fast to build, Python-native |
| Agent orchestration | LangGraph | Industry-standard, same framework BubbleRAN uses |
| Knowledge graph | RDFLib (RDF triples + SPARQL queries) | Proper semantic KG library; scales to production; pure Python, no infra |
| Language | Python 3.10+ | Entire stack is Python |
| LLM for agents | OpenAI API via openai SDK | Available, capable, no GPU needed |

---

## Tech Stack

```
# Phase 1 (already installed)
python 3.10+
networkx          # graph topology / digital twin
streamlit         # UI dashboard
plotly            # interactive topology visualization + telemetry charts
pandas            # telemetry data handling
numpy             # synthetic telemetry generation

# Phase 2 (install now)
rdflib            # RDF knowledge graph with SPARQL query support
langgraph         # agent orchestration (state machine for the self-healing loop)
langchain-core    # base abstractions for tools and messages
openai            # OpenAI API for agent reasoning
```

---

## Project Structure

```
6g-self-healing/
├── CLAUDE.md                  # this file
├── README.md                  # project overview, paper reference, architecture
├── requirements.txt           # python dependencies
├── app.py                     # streamlit entry point
├── twin/
│   ├── __init__.py
│   ├── network.py             # NetworkX topology: nodes, edges, telemetry state
│   ├── dataset.py             # TelecomTS data loading and preprocessing
│   ├── telemetry.py           # telemetry generation: real replay + synthetic
│   └── faults.py              # fault injection: define and trigger fault scenarios
├── knowledge/
│   ├── __init__.py
│   ├── ontology.py            # RDFLib graph: alarm → root cause → remediation triples
│   └── queries.py             # SPARQL query templates for agent lookups
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py        # LangGraph state machine wiring the 4 agents
│   ├── detector.py            # anomaly detection on telemetry streams
│   ├── diagnosis.py           # root cause analysis via KG SPARQL lookup
│   ├── planner.py             # remediation planning + logical twin verification
│   └── executor.py            # apply fix to twin + confirm recovery
├── ui/
│   ├── __init__.py
│   ├── topology.py            # plotly network graph visualization
│   ├── telemetry_chart.py     # time-series telemetry panel
│   └── reasoning_trace.py     # agent reasoning log + KG path visualization
└── data/
    └── telecomts/             # preprocessed real 5G KPI traces
```

---

## Phased Implementation

### Phase 1: Digital Twin + Visual Network Simulation (COMPLETE)

Phase 1 is built and working. The Streamlit dashboard shows a 6G-inspired topology with real TelecomTS radio traces, synthetic core telemetry, 5 injectable faults with cascade propagation, and real/synthetic visual distinction. Do not modify Phase 1 code unless Phase 2 requires a specific integration point.

### Phase 2: Knowledge Graph + Multi-Agent Self-Healing Loop (CURRENT)

**Goal:** When a fault fires, a pipeline of four AI agents autonomously detects the anomaly, diagnoses the root cause by querying a knowledge graph, plans a remediation (verified against the twin), and executes the fix — with every step visible in a reasoning trace panel. The user can toggle between autonomous mode and manual mode.

---

#### 2A. Knowledge Graph (`knowledge/ontology.py`, `knowledge/queries.py`)

**Library:** RDFLib. The KG is an RDF graph of triples using a custom telecom ontology namespace.

**Ontology namespace:** `http://6g-twin/ontology/` (prefix: `TEL`)

**Triple structure:**

```
AlarmPattern  --TEL:indicates-->  RootCause
RootCause     --TEL:resolvedBy--> Remediation
RootCause     --TEL:affects-->    NetworkEntity
Remediation   --TEL:targets-->    NetworkEntity
AlarmPattern  --TEL:metric-->     MetricName
AlarmPattern  --TEL:threshold-->  ThresholdValue
```

**Required triples (one group per fault scenario):**

1. **RF Jammer**
   - AlarmPattern: high BLER (>5%) + low SNR (<15 dB) + low RSRP on radio edge
   - RootCause: `rf_interference`
   - Remediation: `isolate_frequency_band` — in demo: clear the jammer fault
   - Affects: BS1, BS1-UE1 edge

2. **Network Congestion**
   - AlarmPattern: high utilization (>80%) + elevated latency + throughput drop on radio edge
   - RootCause: `radio_congestion`
   - Remediation: `offload_traffic` — in demo: clear the congestion fault
   - Affects: BS2, BS2-UE2 edge

3. **Node Overload**
   - AlarmPattern: CPU >90% + memory >85% + rejected sessions on a base station
   - RootCause: `compute_overload`
   - Remediation: `offload_to_edge_cloud` — in demo: clear the overload fault
   - Affects: BS3, BS3-EDGE2 backhaul

4. **Service Down (SMF)**
   - AlarmPattern: health_check_failed on SMF + latency spike on N11/N4 + session drop on UPF
   - RootCause: `core_function_crash`
   - Remediation: `restart_network_function` — in demo: clear the service_down fault
   - Affects: SMF, AMF-SMF edge, SMF-UPF edge, UPF sessions

5. **SLA Breach**
   - AlarmPattern: gradual throughput decay (>40% drop) + latency creep on EDGE1-UPF
   - RootCause: `path_degradation`
   - Remediation: `reroute_traffic` — in demo: clear the sla_breach fault
   - Affects: EDGE1, EDGE1-UPF edge

**`knowledge/ontology.py` must expose:**
- `build_kg() -> rdflib.Graph` — constructs and returns the populated RDF graph
- `get_kg_networkx(kg) -> nx.DiGraph` — converts to NetworkX for visualization (use `rdflib.extras.external_graph_libs.rdflib_to_networkx_digraph`)

**`knowledge/queries.py` must expose:**
- `find_root_cause(kg, alarm_metrics: dict) -> dict` — takes a dict of {metric: value} pairs from the Detector, runs a SPARQL query matching against AlarmPattern thresholds, returns `{"root_cause": str, "confidence": float, "affected_entities": list, "evidence": list}`
- `find_remediation(kg, root_cause: str) -> dict` — takes a root cause ID, returns `{"action": str, "target_entities": list, "description": str}`
- Both functions return Python dicts, not raw SPARQL results. The agents consume dicts.

**SPARQL matching logic:** The Detector passes observed metric violations (e.g., `{"BS1-UE1.packet_loss_pct": 8.2, "BS1-UE1.snr_db": 12.1}`). The SPARQL query matches these against AlarmPattern nodes whose metric thresholds are violated. If multiple patterns match, rank by number of matching metrics (more specific = higher confidence).

---

#### 2B. Agent Definitions (`agents/`)

All four agents use the OpenAI API (model: `gpt-4o-mini`) via the openai SDK. Each agent is a function that takes structured input and returns structured output. Agents do NOT hold conversation history — each call is stateless with full context passed in.

**Agent 1: Detector (`agents/detector.py`)**

- **Input:** Current tick's telemetry for all entities (from the rolling-window DataFrames)
- **Logic:** Rule-based, NOT LLM-based. Compare each metric against thresholds:
  - Radio edge: BLER > 5%, SNR < 15 dB, throughput drop > 50% from baseline
  - Node: CPU > 90%, memory > 85%, status == "degraded" or "down"
  - Synthetic edge: latency > 3x baseline, utilization > 90%, packet_loss > 2%
  - Gradual: throughput dropped > 40% over last 20 ticks (for SLA breach detection)
- **Output:** `{"anomaly_detected": bool, "violations": [{"entity": str, "metric": str, "value": float, "threshold": float}], "tick": int}`
- **Why rule-based:** Detection thresholds are deterministic. Using an LLM here wastes tokens and adds latency. The LLM reasoning starts at Diagnosis.

**Agent 2: Diagnosis (`agents/diagnosis.py`)**

- **Input:** The Detector's violation list + recent telemetry window (last 10 ticks) for affected entities and their graph neighbors
- **Logic:** LLM-based. The agent receives:
  1. The violation list as structured data
  2. The KG query results from `find_root_cause()` — matching alarm patterns, candidate root causes, and affected entities
  3. Recent telemetry context for the affected entities (so the LLM can see the trend)
  4. The network topology neighbors (so it can reason about cascade direction)
- **System prompt:** "You are a telecom network diagnosis agent. Given the alarm violations, knowledge graph matches, and telemetry context, determine the most likely root cause. Explain your reasoning step by step, citing specific metric values and KG evidence."
- **Output:** `{"root_cause": str, "confidence": float, "reasoning": str, "affected_entities": list, "kg_evidence": list}`
- **The reasoning string is displayed in the UI trace panel.**

**Agent 3: Planner (`agents/planner.py`)**

- **Input:** The Diagnosis output + KG remediation lookup (`find_remediation()`) + current twin state
- **Logic:** LLM-based. The agent receives:
  1. The diagnosed root cause and affected entities
  2. The KG's recommended remediation and target entities
  3. Current state of the target entities (CPU, memory, status, link metrics)
  4. The network topology (dependency graph) so it can assess side effects
- **Twin verification step:** The Planner does NOT run a parallel simulation. Instead, it performs logical verification: given the dependency graph and the proposed action, reason about whether the fix would resolve the issue without creating new problems. Example: "Restarting SMF will restore session management. Dependency graph shows UPF sessions depend on SMF. Predicted outcome: UPF session count recovers, N4 latency normalizes. No negative side effects on AMF or radio edges."
- **System prompt:** "You are a telecom network remediation planner. Given the diagnosis and the knowledge graph's recommended action, verify the proposed fix by reasoning about the network dependency graph. Explain what will happen when the fix is applied, confirm no side effects, and approve or reject the action."
- **Output:** `{"action": str, "target_entities": list, "verification_reasoning": str, "approved": bool, "predicted_outcome": str}`

**Agent 4: Executor (`agents/executor.py`)**

- **Input:** The Planner's approved action + the active faults list + the twin graph
- **Logic:** NOT LLM-based. Deterministic. Maps the Planner's action to a twin operation:
  - `"isolate_frequency_band"` → remove the jammer fault from active_faults
  - `"offload_traffic"` → remove the congestion fault from active_faults
  - `"offload_to_edge_cloud"` → remove the node_overload fault from active_faults
  - `"restart_network_function"` → remove the service_down fault from active_faults
  - `"reroute_traffic"` → remove the sla_breach fault from active_faults
- After applying: wait 5 ticks, then check if the affected entities' metrics have returned to healthy thresholds.
- **Output:** `{"action_taken": str, "success": bool, "recovery_ticks": int, "post_state": dict}`
- **Why not LLM-based:** Execution is a deterministic mapping. No reasoning needed.

---

#### 2C. Orchestration (`agents/orchestrator.py`)

**Framework:** LangGraph state machine.

**State schema:**
```python
class HealingState(TypedDict):
    tick: int
    anomaly: dict | None          # Detector output
    diagnosis: dict | None        # Diagnosis output
    plan: dict | None             # Planner output
    execution: dict | None        # Executor output
    status: str                   # "idle" | "detecting" | "diagnosing" | "planning" | "executing" | "resolved" | "failed"
    trace: list[dict]             # ordered log of all agent outputs for the UI
```

**Flow:**
```
[idle] → Detector fires every tick
    → if no anomaly: stay idle
    → if anomaly detected: → [detecting]
        → Diagnosis agent called → [diagnosing]
            → Planner agent called → [planning]
                → if approved: Executor called → [executing]
                    → wait for recovery → [resolved] or [failed]
                → if not approved: → [failed] with reason
```

**Debounce:** After the Detector flags an anomaly, wait 3 ticks of sustained violation before triggering Diagnosis. This prevents false positives from transient noise spikes.

**Cooldown:** After a healing cycle completes (resolved or failed), enter a 10-tick cooldown before the Detector can trigger again. Prevents rapid re-triggering.

**Auto-heal toggle:** Exposed in the Streamlit sidebar.
- **ON:** The full loop runs autonomously. Faults are detected and healed without user intervention.
- **OFF:** The Detector and Diagnosis run (so the user sees the reasoning), but the Planner/Executor do NOT run. The user sees "Recommended action: X" and can click a button to apply it manually.

---

#### 2D. Reasoning Trace Panel (`ui/reasoning_trace.py`)

**Location:** Below the telemetry charts in the main area, OR as a third column on the right.

**Content:** A scrollable log showing each agent's output in sequence when a healing cycle runs:

1. **Detection** — "Anomaly detected at tick 234: BS1-UE1 packet_loss_pct = 8.2% (threshold: 5%), BS1-UE1 snr_db = 12.1 dB (threshold: 15 dB)"

2. **Diagnosis** — "Root cause: RF Interference (confidence: 0.92). Evidence: KG pattern match — high BLER + low SNR indicates rf_interference. Telemetry shows SNR dropped from 21 dB to 12 dB over 5 ticks, consistent with jammer onset. Affected: BS1, BS1-UE1."
   - **KG path highlight:** Show the matched path in the knowledge graph: `[high_bler+low_snr] --indicates--> [rf_interference] --resolvedBy--> [isolate_frequency_band]`. Render this as a small inline Plotly directed graph with the matched nodes highlighted. This is the KG visualization.

3. **Planning** — "Proposed action: Isolate frequency band on BS1. Verification: restarting on the isolated band will restore SNR and reduce BLER. Dependency check: no downstream impact on EDGE1 or core. Approved: yes"

4. **Execution** — "Action applied at tick 237. Recovery confirmed at tick 242: BS1-UE1 SNR = 21.3 dB, BLER = 0.1%."

**Formatting:**
- Each step is a collapsible expander (Streamlit `st.expander`)
- Timestamps (tick numbers) on each step
- Color-coded: detection=yellow, diagnosis=blue, planning=purple, execution=green/red
- The KG path visualization appears inside the Diagnosis expander

---

#### 2E. Integration with Phase 1

**Changes to existing Phase 1 code (keep minimal):**

- `app.py`: Add the auto-heal toggle in the sidebar. Add the reasoning trace panel. Call the orchestrator on each tick when auto-heal is ON.
- `twin/faults.py`: Add a `remove_fault(active_faults, fault_name)` function that the Executor calls to clear a resolved fault.
- `twin/telemetry.py`: No changes needed. The Detector reads from the existing rolling-window DataFrames.
- `twin/network.py`: No changes needed.
- `ui/`: Add `reasoning_trace.py`. Do not modify `topology.py` or `telemetry_chart.py`.

---

#### 2F. Success Criteria for Phase 2

- `streamlit run app.py` still works (Phase 1 unbroken)
- With auto-heal OFF: inject a fault → Detector flags it → Diagnosis shows root cause with KG evidence → Planner shows recommended action → user clicks to apply → Executor resolves it → reasoning trace shows full pipeline
- With auto-heal ON: inject a fault → entire detect→diagnose→plan→execute loop runs autonomously → fault resolves → reasoning trace shows the full pipeline without user intervention
- The KG path visualization renders in the Diagnosis step
- Each agent's reasoning is visible and readable in the trace panel
- All 5 fault types can be detected, diagnosed, and resolved
- OpenAI API calls work (requires OPENAI_API_KEY env var)

#### 2G. What Phase 2 is NOT

- Do not build a chat interface. The agents are a pipeline, not a conversation.
- Do not add streaming token display. The reasoning trace shows complete outputs.
- Do not refactor Phase 1 storage, DataFrames, or the simulation loop. Work with what exists.
- Do not add user authentication or API key management UI. Use env vars.
- Do not build custom LangGraph tool schemas for every function. Keep tools simple: Python functions the orchestrator calls directly.

---

### Phase 3: Polish + README

- Architecture diagram in README (the detect→diagnose→plan→execute flow with KG and twin)
- Paper citations (Section 3, Section 3.3) with specific quotes
- Nokia KG blog reference
- Framing: "proof-of-concept of Pillar 2"
- Screen recording / GIF of the full auto-heal demo
- Future work section: RL agents (Section 3.1), Raspberry Pi hardware deployment, Open5GS integration, MCS columns in TelecomTS

---

## Naming and Style Conventions

- Snake_case for all Python files and functions
- Type hints on all function signatures
- Docstrings on public functions (one-liner is fine)
- No classes where a function suffices (exception: LangGraph state is a TypedDict)
- Streamlit page config: `page_title="6G Self-Healing Network"`, `layout="wide"`
- Color scheme: use a dark theme consistent with network monitoring dashboards. Plotly dark template.
- Node status colors: healthy=`#00CC66`, degraded=`#FFAA00`, down=`#FF3333`
- Reasoning trace colors: detection=`#FFAA00`, diagnosis=`#4A9EFF`, planning=`#AA66FF`, execution=`#00CC66`

---

## Key Constraints

- **Phase 1 is frozen.** Do not modify Phase 1 files unless Phase 2 requires a specific, minimal integration point (listed in 2E above).
- **No GPU needed.** Everything runs on a standard laptop.
- **Keep dependencies minimal.** Only add a package if it saves significant code. Prefer stdlib.
- **Do not create placeholder files.** Every file created must contain working code.
- **OpenAI API calls require `OPENAI_API_KEY` env var.** Do not hardcode keys. Fail gracefully if the key is missing (show a warning in the UI, disable auto-heal).
- **LLM calls are expensive.** The Detector and Executor are rule-based, NOT LLM-based. Only Diagnosis and Planner use Claude. This is a deliberate architectural choice, not a cost-cutting shortcut — detection is deterministic and execution is a mapping; neither benefits from LLM reasoning.

---

## Context: Why This Project Exists

This project demonstrates enthusiasm and technical understanding for a Fall 2026 internship application to Nokia's Applied AI Research team (Sunnyvale), led by Liang Wu and Kelly Wan. Kelly's title is "Head of AI Agentic Intelligence" — her self-described work is "autonomous AI agents and reasoning frameworks to enhance telecom network operations" and "improving system reliability." This project directly maps to her mandate.

The paper (Wu et al., KDD 2026) is a BlueSky Vision paper — it proposes the architecture but has not been implemented. The two supporting infrastructure components (digital twin and knowledge graph) are described in Section 3.3 as "not yet existing in deployable form." This project prototypes a working miniature of that missing infrastructure.

**Do not mention this internship context in any code, comments, or UI.** The project should stand on its own as a technical artifact.
# CLAUDE.md

## Project: Self-Healing 6G Network — Proof of Concept

A proof-of-concept of the multi-agent self-healing architecture proposed in Wu et al. (KDD 2026), "Towards Resilient and Autonomous Networks: A BlueSky Vision on AI-Native 6G." Demonstrates the autonomous detect → diagnose → recover loop from Section 3, grounded by the two infrastructure components from Section 3.3: a network digital twin and a telecommunications knowledge graph.

**Paper reference:** https://arxiv.org/abs/2605.21395

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
| Telemetry data | Seeded from real 5G KPI data (BubbleRAN historical CSV) | Real signal characteristics without running a full 5G stack |
| UI framework | Streamlit | Matches BubbleRAN ecosystem, fast to build, Python-native |
| Agent orchestration | LangGraph (Phase 2) | Industry-standard, same framework BubbleRAN uses |
| Knowledge graph | Hardcoded Python dict/JSON (Phase 2) | Small scope, no need for Neo4j or a graph DB |
| Language | Python 3.10+ | Entire stack is Python |
| LLM for agents | Claude API via Anthropic SDK (Phase 2) | Available, capable, no GPU needed |

---

## Tech Stack

```
python 3.10+
networkx          # graph topology / digital twin
streamlit         # UI dashboard
plotly            # interactive topology visualization + telemetry charts
pandas            # telemetry data handling
numpy             # synthetic telemetry generation
```

Phase 2 additions (do not install yet):
```
langgraph         # agent orchestration
anthropic         # Claude API for agent reasoning
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
│   ├── telemetry.py           # telemetry generation: baseline from real KPI data + noise
│   └── faults.py              # fault injection: define and trigger fault scenarios
├── knowledge/                 # Phase 2
│   ├── __init__.py
│   └── graph.py               # knowledge graph: alarm → root cause → remediation
├── agents/                    # Phase 2
│   ├── __init__.py
│   ├── detector.py            # anomaly detection on telemetry streams
│   ├── diagnosis.py           # root cause analysis via KG lookup
│   ├── planner.py             # remediation planning + twin verification
│   └── executor.py            # apply fix + confirm recovery
├── ui/
│   ├── __init__.py
│   ├── topology.py            # plotly network graph visualization
│   ├── telemetry_chart.py     # time-series telemetry panel
│   └── reasoning_trace.py     # Phase 2: agent reasoning log panel
└── data/
    └── historical_kpi.csv     # real 5G KPI data (from BubbleRAN or similar)
```

---

## Phased Implementation

### Phase 1: Digital Twin + Visual Network Simulation (CURRENT)

**Goal:** A running Streamlit app that shows a 6G-inspired network topology, generates live telemetry, and lets the user inject faults visually. This must be demoable standalone — no agents needed yet.

**Scope:**

1. **Network topology (`twin/network.py`)**
   - Build a NetworkX graph representing a small 6G-inspired network
   - Node types: `base_station` (3-4), `core_function` (AMF, SMF, UPF — from the paper's Section 3.2), `edge_cloud` (1-2), `ue_cluster` (user equipment groups, 2-3)
   - Edges represent links between them with attributes: `bandwidth`, `latency_baseline`, `utilization_baseline`
   - Each node has attributes: `type`, `status` (healthy/degraded/down), `cpu_utilization`, `memory_utilization`
   - The topology should loosely mirror the paper's RAN-side + core-side architecture (Section 3.1, 3.2)

2. **Telemetry generation (`twin/telemetry.py`)**
   - Each edge emits telemetry every tick: `latency_ms`, `throughput_mbps`, `packet_loss_pct`, `utilization_pct`
   - Each node emits: `cpu_pct`, `memory_pct`, `active_sessions`
   - Baseline values should feel realistic (use BubbleRAN KPI ranges if CSV is available, else use sensible 5G defaults: ~3-10ms latency, 100-500 Mbps throughput, <1% packet loss)
   - Add Gaussian noise on each tick so charts look alive
   - Store telemetry as a rolling window (last N ticks) in a pandas DataFrame per entity

3. **Fault injection (`twin/faults.py`)**
   - Define 3-4 fault scenarios as simple dataclasses:
     - `LinkCongestion`: spike latency + utilization on a specific edge
     - `NodeOverload`: spike CPU on a base station (the autonomous vehicle scenario from the paper)
     - `ServiceDown`: set a core function (e.g., SMF) status to "down", degrade connected edges
     - `SLABreach`: gradually degrade throughput on a path below threshold
   - Each fault has: `name`, `target` (node/edge id), `effect` (dict of metric overrides), `duration_ticks`
   - Faults are triggered via Streamlit sidebar buttons
   - Active faults modify telemetry output on affected entities

4. **Streamlit UI (`app.py` + `ui/`)**
   - **Left sidebar:** fault injection buttons, simulation controls (start/pause/speed), current tick counter
   - **Main area, top:** interactive network topology graph (plotly). Nodes colored by status (green/yellow/red). Edges colored by utilization. Click a node/edge to select it.
   - **Main area, bottom:** telemetry time-series chart for selected node/edge. Show last 60 ticks. Clearly mark the moment a fault was injected.
   - Use `st.empty()` containers and a loop with `time.sleep()` for live updating, OR use `st_autorefresh` — pick whichever is simpler
   - The topology must update colors in real-time as faults fire and resolve

**Success criteria for Phase 1:**
- `streamlit run app.py` launches a working dashboard
- Topology renders with correct node types and link structure
- Telemetry charts show live-updating metrics with realistic noise
- Clicking "Inject: Link Congestion" visibly changes the affected edge color and spikes the telemetry chart
- Fault resolves after its duration and metrics return to baseline
- The whole thing looks clean enough to screenshot for a README

**What Phase 1 is NOT:**
- No agents. No LLM calls. No knowledge graph. No healing. Those are Phase 2.
- No authentication, no persistence, no deployment config.
- No over-designed component system. Streamlit is intentionally simple — keep it that way.

### Phase 2: Knowledge Graph + Multi-Agent Self-Healing Loop

Build after Phase 1 is solid. Adds:
- Knowledge graph mapping alarm signatures → root causes → remediations
- Four agents (Detector, Diagnosis, Planner, Executor) orchestrated via LangGraph
- Planner tests proposed fix in the digital twin before applying
- Reasoning trace panel in the UI showing each agent's step
- "Auto-heal" toggle: when ON, agents handle faults autonomously; when OFF, user sees the diagnosis but applies fixes manually

### Phase 3: Polish + README

- Architecture diagram in README
- Paper citations (Section 3, Section 3.3)
- Framing: "proof-of-concept of Pillar 2"
- Screen recording / GIF of the demo
- Note on future integration with Open5GS/UERANSIM

---

## Naming and Style Conventions

- Snake_case for all Python files and functions
- Type hints on all function signatures
- Docstrings on public functions (one-liner is fine)
- No classes where a function suffices
- Streamlit page config: `page_title="6G Self-Healing Network"`, `layout="wide"`
- Color scheme: use a dark theme consistent with network monitoring dashboards. Plotly dark template.
- Node status colors: healthy=`#00CC66`, degraded=`#FFAA00`, down=`#FF3333`

---

## Key Constraints

- **No network access needed for Phase 1.** All telemetry is simulated locally. Do not fetch external APIs.
- **No GPU needed.** Everything runs on a standard laptop.
- **Keep dependencies minimal.** Only add a package if it saves significant code. Prefer stdlib.
- **Do not create placeholder files.** Every file created must contain working code.
- **Do not add Phase 2 code during Phase 1.** Create the directories but leave Phase 2 files empty or absent.

---

## Context: Why This Project Exists

This project demonstrates enthusiasm and technical understanding for a Fall 2026 internship application to Nokia's Applied AI Research team (Sunnyvale), led by Liang Wu and Kelly Wan. Kelly's title is "Head of AI Agentic Intelligence" — her self-described work is "autonomous AI agents and reasoning frameworks to enhance telecom network operations" and "improving system reliability." This project directly maps to her mandate.

The paper (Wu et al., KDD 2026) is a BlueSky Vision paper — it proposes the architecture but has not been implemented. The two supporting infrastructure components (digital twin and knowledge graph) are described in Section 3.3 as "not yet existing in deployable form." This project prototypes a working miniature of that missing infrastructure.

**Do not mention this internship context in any code, comments, or UI.** The project should stand on its own as a technical artifact.
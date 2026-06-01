# Self-Healing 6G Network — Proof of Concept

A working miniature of the autonomous **detect → diagnose → plan → execute** loop from
Wu et al. (KDD 2026), *"Towards Resilient and Autonomous Networks: A BlueSky Vision on
AI-Native 6G,"* grounded by the two infrastructure components from §3.3: a **network
digital twin** and a **telecom knowledge graph**.

A NetworkX digital twin streams live telemetry; when a fault fires, a pipeline of four
agents detects the anomaly, diagnoses the root cause against an RDF knowledge graph,
plans a verified remediation, and applies it — with every step shown in a reasoning trace.

```bash
pip install -r requirements.txt
python -m twin.dataset        # one-time: build the real 5G traces
echo "OPENAI_API_KEY=sk-..." > .env
streamlit run app.py
```

---

## Data

Radio-access edges (UE↔base-station) **replay real 5G KPI traces** from the
**TelecomTS** dataset (arXiv:2510.06063), preprocessed into `data/telecomts/*.csv`:

| KPI | Source metric |
|---|---|
| `throughput_mbps` | TX+RX bytes → Mbps |
| `packet_loss_pct` | DL BLER |
| `utilization_pct` | PRB utilization |
| `snr_db`, `rsrp_dbm` | UL SNR, RSRP |

Five traces are used: ZoneA/YouTube (normal + jammer), ZoneB/Twitch (normal +
congestion), ZoneC/File (normal). Everything else — core functions (AMF/SMF/UPF),
edge clouds, and backhaul/signaling links — is **synthetic**, visually distinguished in
the topology (solid = real, dashed = synthetic).

## Noise

Synthetic telemetry is not plain Gaussian — telecom traffic is bursty and
non-stationary, so the generator (`twin/telemetry.py`) layers:

- **diurnal drift** — a slow sine modulating baselines (time-of-day load)
- **micro-bursts** — Poisson-triggered short spikes on data-plane links
- **Gaussian jitter** — a small ambient noise floor
- **correlated degradation** — node CPU couples into its links' latency/throughput, so
  load propagates through the dependency graph (how cascades travel)

## Fault Injection Strategy

Five scenarios (`twin/faults.py`), each a **primary effect plus cascades** through the
dependency graph — the propagation the Diagnosis agent must untangle:

| Fault | Primary effect | Cascade |
|---|---|---|
| RF Jammer | BS1↔UE1 → real jammer trace | CPU load on BS1 → backhaul/N2 |
| Congestion | BS2↔UE2 → real congestion trace | CPU load on BS2 → backhaul |
| Node Overload | BS3 CPU/mem spike, sessions rejected | elevated CPU → its links |
| Service Down | SMF taken DOWN | N4/N11 latency + UPF session drop |
| SLA Breach | EDGE1↔UPF gradual throughput decay | latency creep, no sudden spike |

Every fault flips a node's operational **status** (DEGRADED/DOWN) — a deterministic,
noise-proof signal that anchors detection (the real radio traces are too noisy for raw
KPI thresholds alone). The affected entity uniquely localizes each root cause.

## Agent Architecture

A **LangGraph** state machine drives the loop once per tick (with debounce + cooldown).
Detection and execution are deterministic; only Diagnosis and Planning use an LLM:

```
Detector  ──▶ Diagnosis ──▶ Planner ──▶ Executor ──▶ recovery
(rules)       (LLM + KG)     (LLM)       (deterministic)
```

- **Detector** (rule-based) — threshold violations on the telemetry window; anchored on node status.
- **Diagnosis** (LLM + KG) — SPARQL match against the RDF knowledge graph
  (`AlarmPattern → RootCause → Remediation`, scored on metric + affected-entity overlap);
  the LLM explains the evidence.
- **Planner** (LLM) — logically verifies the KG-recommended fix against the dependency
  graph (no side effects) and approves/rejects.
- **Executor** (deterministic) — applies the fix to the twin and confirms recovery.

**Knowledge graph** (`knowledge/`): RDF triples + SPARQL, grounding diagnosis and the
inline KG-path visualization. **Auto-heal** runs the full loop autonomously; **manual**
mode stops after diagnosis for one-click approval.

## Tech Stack

| Layer | Tool |
|---|---|
| Digital twin | NetworkX |
| Knowledge graph | RDFLib (RDF + SPARQL) |
| Agent orchestration | LangGraph |
| LLM reasoning | OpenAI `gpt-4o-mini` |
| UI / viz | Streamlit + Plotly |
| Data | pandas, numpy (TelecomTS traces) |

Pure Python 3.10+, no GPU, runs on a laptop.

# ⏱ Time Machine

**Paste an incident ID → the agent rewinds the timeline, finds root cause, and simulates the fix in a sandbox — live.**

Hackathon scaffold. Pure Python **stdlib, zero dependencies**. Deterministic mock
"intelligence" so it runs with no API keys; real Azure AI Foundry + MCP calls plug
into a single marked hook.

## Run

```bash
cd ~/hackathon/time-machine
python3 server.py
# open http://localhost:8011
```

Try incident IDs: **`INC-4471`** (connection-pool exhaustion) or **`INC-5090`** (OOMKill loop),
or click **Samples**.

## Demo flow (3 min)
1. Paste `INC-4471` → **Rewind**. Timeline animates the spike + the bad deploy.
2. Root cause appears with confidence % and the offending diff.
3. **Simulate fix in sandbox** → PR opens, metrics graph goes **red → green**.

## Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/incidents` | list replayable incidents |
| GET | `/api/replay?id=INC-4471` | timeline + root cause |
| GET | `/api/fix?id=INC-4471` | apply fix in sandbox + recovery metrics |

## Where the real magic plugs in (`server.py`)
- `analyze_incident()` → replace mock lookup with **MCP** pulls (Prometheus/Loki + GitHub + AKS)
  correlated by an **Azure AI Foundry agent**.
- `apply_fix_in_sandbox()` → replace with real `kubectl`/`helm` apply into a sandbox
  namespace + poll Prometheus for the recovered series.
- Incident data lives in `incidents.json` — add your own replayable incidents there.

## Why it wins
Most AIOps tools *explain*. This one *reproduces and remediates* live — root cause to
verified fix in one flow. Reuses MCP/AKS/agent plumbing you already know.

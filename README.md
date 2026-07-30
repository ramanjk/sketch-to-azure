# 🎨 Sketch Ops — AI agents that turn diagrams and incidents into action

> **Microsoft Hackathon project.** Two AI-agent demos that collapse the gap
> between *intent* and *running infrastructure*, built on Azure OpenAI + the
> Azure CLI, with **zero Python dependencies** (pure stdlib).

| | Project | One-liner | Status |
|---|---|---|---|
| ✏️ | **[Whiteboard → Running App](whiteboard-to-app/)** | Snap a photo of an architecture diagram → GPT-4o parses it → generates **compile-valid Bicep** → **really deploys** the safe subset to Azure. | ✅ Live vision + real deploy working |
| ⏱ | **[Time Machine](time-machine/)** | Paste an incident ID → agent rewinds the timeline, finds root cause, and simulates the fix red→green. | ✅ Demo working (mock data) |

---

## Why this is interesting

Both projects are **agentic operations** demos: a model reasons over a messy,
human artifact (a hand-drawn diagram, a production incident) and produces a
**verifiable, executable** result — not just a chat answer.

- **Whiteboard → App** proves the loop *image → structured graph → IaC → real
  Azure resources*. The vision parse is real (Azure OpenAI GPT-4o), the Bicep is
  real (verified with `az bicep build`), and the deploy is real (`az deployment
  group create` into a dedicated resource group). Heavy resources (App
  Gateway/APIM/AKS) are validated-only; a cheap, fast subset (Managed Identity +
  Key Vault + ACR) is actually provisioned so the demo lands live on stage.
- **Time Machine** proves the loop *incident → timeline → root cause → simulated
  fix*, the AIOps "holy grail" of not just explaining an outage but reproducing
  and remediating it.

## Quick start

Both run with **only Python 3** — no `pip install`, no packages.

```bash
# ✏️ Whiteboard → App  (offline mock: no cloud needed)
cd whiteboard-to-app && python3 server.py         # http://localhost:8012

# ⏱ Time Machine
cd time-machine && python3 server.py              # http://localhost:8011
```

For **live GPT-4o vision + real Azure deploy**, see
[whiteboard-to-app/README.md](whiteboard-to-app/README.md) (`./run-live.sh`).

## Architecture

```
        ┌── image ──►  GPT-4o vision  ──►  {nodes, edges} graph
Whiteboard→App                                   │
        │                                        ▼
        │                          Bicep generator (azure_iac.py)
        │                                        │
        │            ┌─────── az bicep build (validate ALL) ───────┐
        └────────────┤                                             │
                     └─ az deployment group create (deploy SAFE subset)

Time Machine:  incident id ─► correlate timeline ─► root-cause reasoning
                              ─► simulate fix in sandbox ─► red→green metrics
```

## Tech

- **Azure OpenAI** GPT-4o / GPT-4.1 vision (structured JSON output)
- **Azure CLI** for AAD auth, `bicep build`, and `deployment group create`
- **Bicep** IaC generation for 11+ Azure resource types
- **Pure Python stdlib** HTTP servers + vanilla JS UIs (no frameworks, no deps)

## Repository layout

```
whiteboard-to-app/   # Project 1: diagram → Bicep → real Azure deploy
  server.py          #   stdlib HTTP server + vision + deploy orchestration
  azure_iac.py       #   Bicep generation (full template + demo-safe subset)
  sketches.json      #   sample architecture patterns
  run-live.sh        #   launch with live vision + real deploy
  cleanup-demo.sh    #   remove demo resources between runs
  static/index.html  #   UI
time-machine/        # Project 2: incident replay & fix
  server.py, incidents.json, static/index.html
```

## Safety & cost notes

- No secrets in the repo. Live mode authenticates via your `az login` token;
  copy `.env.example` → `.env` (gitignored) for any local overrides.
- Real deploys target a **dedicated** resource group and create only cheap
  resources. Run `cleanup-demo.sh` after each rehearsal. ACR Basic ≈ $0.17/day;
  Managed Identity and Key Vault are effectively free at rest.

## Author

Kuruva Ramanjaneyulu (Ram) · built for the Microsoft Hackathon.

## License

[MIT](LICENSE)

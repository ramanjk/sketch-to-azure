# ✏️ Sketch → Azure — turn a diagram photo into real Azure infrastructure

> **Microsoft Hackathon project.** An AI agent that collapses the gap between
> *intent* and *running infrastructure*: snap a photo of an architecture
> diagram → GPT-4o parses it → it generates **compile-valid Bicep** → and
> **really deploys** the safe subset to Azure. Built on Azure OpenAI + the
> Azure CLI, with **zero Python dependencies** (pure stdlib).

<p align="center">
  <img src="docs/demo.gif" alt="Sketch → Azure: a photo of an architecture diagram becomes validated Bicep and real Azure resources" width="760">
</p>

<p align="center">
  <b>▶ Prefer video?</b> <a href="docs/demo.mp4">Watch the 20-second MP4 walkthrough</a>
  &nbsp;·&nbsp; photo → GPT-4o vision → Bicep → real deploy
</p>

---

## Why this is interesting

This is an **agentic operations** demo: a model reasons over a messy, human
artifact (a hand-drawn or exported architecture diagram) and produces a
**verifiable, executable** result — not just a chat answer.

It proves the full loop *image → structured graph → IaC → real Azure
resources*:

- The **vision parse is real** — Azure OpenAI GPT-4o returns a structured
  `{nodes, edges}` graph.
- The **Bicep is real** — verified with `az bicep build`.
- The **deploy is real** — `az deployment group create` into a dedicated
  resource group.

Heavy resources (App Gateway / APIM / AKS) are **validated-only** because they
take many minutes and cost money; a cheap, fast subset (Managed Identity +
Key Vault + ACR) is **actually provisioned** so the demo lands live on stage.

## Quick start

Runs with **only Python 3** — no `pip install`, no packages.

```bash
# offline mock (no cloud needed) — great for a first look
cd whiteboard-to-app && python3 server.py         # http://localhost:8012
```

For **live GPT-4o vision + real Azure deploy**, see
[whiteboard-to-app/README.md](whiteboard-to-app/README.md) (`./run-live.sh`).

## Architecture

```
  ┌── image ──►  GPT-4o vision  ──►  {nodes, edges} graph
  │                                       │
  │                                       ▼
  │                         Bicep generator (azure_iac.py)
  │                                       │
  │           ┌─────── az bicep build (validate ALL) ───────┐
  └───────────┤                                             │
              └─ az deployment group create (deploy SAFE subset)
```

## Tech

- **Azure OpenAI** GPT-4o / GPT-4.1 vision (structured JSON output)
- **Azure CLI** for AAD auth, `bicep build`, and `deployment group create`
- **Bicep** IaC generation for 11+ Azure resource types
- **Pure Python stdlib** HTTP server + vanilla JS UI (no frameworks, no deps)

## Repository layout

```
whiteboard-to-app/   # the app
  server.py          #   stdlib HTTP server + vision + deploy orchestration
  azure_iac.py       #   Bicep generation (full template + demo-safe subset)
  sketches.json      #   sample architecture patterns
  run-live.sh        #   launch with live vision + real deploy
  cleanup-demo.sh    #   remove demo resources between runs
  static/index.html  #   UI
docs/                # demo GIF + MP4
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

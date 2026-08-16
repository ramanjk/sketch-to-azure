# ✏️ Whiteboard → Running App

**Snap a photo of an architecture sketch → parsed graph → generated IaC → a live URL.**

<p align="center">
  <img src="../docs/demo.gif" alt="Whiteboard to Azure demo" width="720">
</p>

Hackathon scaffold. Pure Python **stdlib, zero dependencies**. Runs fully offline
with a deterministic mock, **or with LIVE GPT-4o vision + real Bicep validation**
when Azure is configured.

## Run

### Live mode (real GPT-4o vision + real Azure deploy)
```bash
cd ~/hackathon/whiteboard-to-app
./run-live.sh          # uses your az login; no secrets in the repo
# open http://localhost:8012  -> badge shows 🟢 live
```
Upload a photo of a real Azure architecture diagram → GPT-4o parses it into a
graph → the generator emits a **compile-valid Bicep** template → the deploy step:
1. runs `az bicep build` on the **full** template (proves all resources compile to ARM), and
2. **really provisions the demo-safe subset** (Managed Identity + Key Vault +
   ACR Basic) into a **dedicated** resource group (`rg-whiteboard-demo`).

Heavy resources (App Gateway/WAF, APIM, AKS, VMs) stay **validate-only** because
they take many minutes and cost money — wrong for a live demo. Verified
end-to-end on a private-AKS diagram → 14 ARM resources compiled + 3 real
resources created.

The upload and agent APIs also accept Microsoft Visio `.vsdx` files. VSDX
packages are parsed natively for page shapes, labels, Azure icon masters,
coordinates, and connectors; no image preview or LibreOffice conversion is
required.

**Clean up between demos** (each run creates uniquely-named resources):
```bash
./cleanup-demo.sh      # removes id-wb-*, kv-wb-*, acrwb* from the demo RG
```

Deploy behavior is controlled by env (set in `run-live.sh`):
- `DEPLOY_RG` — target RG for the real subset deploy (default `rg-whiteboard-demo`)
- `DEPLOY_MODE=real` — provision the safe subset (default when `DEPLOY_RG` set)
- `DEPLOY_MODE=whatif` — instead run `az deployment group what-if` on the full template
- unset — validate only, no provisioning

### Offline mode (mock, no cloud)
```bash
cd ~/hackathon/whiteboard-to-app
python3 server.py      # badge shows 🟡 mock
# open http://localhost:8012
```

## Demo flow (3 min)
1. Click a sample sketch (or upload a whiteboard photo).
2. Watch the **parsed graph** pop node-by-node.
3. **Generate IaC** → real Bicep + Kubernetes manifests appear.
4. **Deploy to sandbox** → a **live URL** appears.
5. Pick the "+ cache" sample to show the graph/IaC change (the redraw-and-diff moment).

## Sketch patterns (`sketches.json`)
| id | Architecture |
|---|---|
| `webapp-basic` | Browser → API → Postgres |
| `webapp-cache` | + Redis cache |
| `event-driven` | API → Service Bus → Worker → Blob |
| `microservices` | Browser → Gateway → Orders/Users → Postgres/Redis |
| `static-site-cdn` | Browser → Front Door/CDN → Static Web App + Functions API → Cosmos |
| `aks-gpu` | Client → AI Gateway → vLLM GPU inference → Blob (model weights) |

## Two generation modes
The generator auto-detects the diagram type:

**A. App patterns** (web/microservice sketches) → **Bicep + Kubernetes**:
- Bicep for managed resources: Postgres, Redis, Service Bus, Storage, Front Door/CDN, Static Web App.
- Kubernetes for `frontend`/`api`/`worker`/`gateway`/`gpu`: Deployment+Service, Ingress
  for public types, GPU nodeSelector + `nvidia.com/gpu`, edge-based `*_URL` env wiring,
  and NetworkPolicy egress rules from the edges.

**B. Azure infrastructure diagrams** (App Gateway, APIM, AKS, Key Vault, ...) →
**a single compile-valid Bicep template** (`azure_iac.py`). Supported node types:
`appgateway`, `waf`, `apim`, `aks`, `keyvault`, `acr`, `appconfig`,
`managedidentity`, `vm`, `privatedns`, `privateendpoint` (+ VNet/subnets/PIP/NIC
scaffolding). Every block is verified to pass `az bicep build`.

Detailed network diagrams additionally preserve individual `vnet`, `subnet`,
`nsg`, `loadbalancer`, and `vm` instances, visible CIDRs, tier placement,
public/internal load balancers, backend-pool membership, and database workload
labels. Required Azure scaffolding not shown in the diagram is returned as an
explicit warning instead of being silently hidden.

Named Azure services outside the deterministic catalog are preserved as
generic Azure resource nodes rather than coerced into the wrong service. A
bounded AI generation-and-repair loop emits Bicep, compiles it, feeds compiler
diagnostics back for up to three attempts, and reports assumptions or
unsupported resources explicitly. Preview uses the exact signed Bicep returned
at analysis time; it never regenerates a different template.

AKS deployment diagrams distinguish the cluster from the applications running
on it. Dockerfiles are build artifacts, container images are image artifacts,
and Kubernetes icons are workloads. The generator emits one AKS cluster, ACR
with `AcrPull`, and one Deployment+Service manifest per workload. A public
load-balancer icon becomes a Kubernetes `LoadBalancer` Service rather than an
unattached standalone Azure Load Balancer.

## Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/config` | reports vision mode (`live` / `mock`) |
| GET | `/api/samples` | list sample sketches |
| GET | `/api/parse?sample=microservices` | sketch → graph |
| POST | `/api/parse-image` | uploaded image → graph (real vision or mock) |
| POST | `/api/generate` | graph → Bicep (+ K8s for app patterns) |
| POST | `/api/deploy` | app: mock URL · azure-infra: **real `az bicep build`** validation |
| POST | `/api/agent/analyze` | authenticated image → graph + IaC + signed plan |
| POST | `/api/agent/preview` | authenticated signed plan → validation + Azure what-if |
| POST | `/api/agent/deploy` | approval-gated deployment of the safe subset |

## Microsoft 365 Copilot agent

The `copilot-studio/` folder contains an importable custom connector OpenAPI
contract, agent instructions, and the Power Automate approval-flow setup. Agent
endpoints require `AGENT_API_KEY`, reject mock vision results, validate all
model-produced graph fields, sign immutable plans, and accept deployment only
after an approval ID is supplied. See
[`copilot-studio/README.md`](copilot-studio/README.md) for setup and publishing.
The included `deploy-container-app.sh`, `Dockerfile`, and `infra/` templates
provision the HTTPS API on Azure Container Apps with managed identity.

## Real GPT-4o vision + auth
`run-live.sh` configures the endpoint/deployment and lets the server authenticate
via your **Azure CLI login** (AAD token) — used when the resource has key-auth
disabled. Auth priority in `server.py`:
1. `AZURE_OPENAI_API_KEY` → `api-key` header
2. `AZURE_OPENAI_TOKEN` → Bearer
3. `az account get-access-token` → Bearer (auto-fetched, cached)

```bash
export AZURE_OPENAI_ENDPOINT="https://<your-aoai>.openai.azure.com"
export AZURE_OPENAI_DEPLOYMENT="gpt-4.1"     # or gpt-4o (vision-capable)
export AZURE_OPENAI_API_VERSION="2025-01-01-preview"
# key optional; without it the server uses your az login
./run-live.sh
```

The UI badge shows 🟢 live or 🟡 mock. All calls use pure stdlib `urllib` (no SDK/pip).
Set `DEPLOY_RG=<rg>` to also run a real `az deployment group what-if` preview.

## Where the real magic plugs in
- `_azure_vision_parse()` (server.py) → GPT-4o vision structured-output call.
- `azure_iac.py` → Azure Bicep templates; extend `AZURE_TYPES` + block builders for more services.
- `architecture_patterns.json` → source-attributed reference guidance selected
  from detected services and supplied to generic IaC generation. Guidance is
  advisory and never authorizes inventing resources absent from the diagram.
- Image ingestion detects SVG content even when a downloaded Architecture
  Center file has a misleading extension, and securely extracts labeled shapes
  before AI graph parsing.
- `validate_bicep()` / `_what_if()` → real Bicep compile + optional what-if preview.
- `deploy()` → swap the sandbox URL for a real `az deployment group create` when ready.
- App-pattern logic: `generate_iac()`, `BICEP_FOR`, `K8S_KINDS`, `sketches.json`.

## Demo-safety tips
- Pre-warm the sandbox (AKS/Container Apps) so deploy is an *apply*, not a cold start.
- Keep vision to 3–4 recognizable patterns for reliable on-stage parsing.

## Why it wins
Pure visual magic — hand-drawn boxes to a clickable running app in under two minutes.
Broadest judge appeal.

#!/usr/bin/env python3
"""Whiteboard -> Running App (hackathon scaffold).

Pure Python stdlib, no external deps. Run:  python3 server.py
Then open http://localhost:8012

Flow: pick/upload a sketch -> parse to a graph -> generate IaC (Bicep + K8s) ->
"deploy" -> live URL. The vision parse and the deploy are mocks so the demo runs
with zero API keys / zero cloud. Marked hooks show exactly where GPT-4o vision
and Azure/GitHub MCP calls go.
"""
import json
import os
import time
import hashlib
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import azure_iac

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8012"))

with open(os.path.join(HERE, "sketches.json"), encoding="utf-8") as f:
    SKETCHES = json.load(f)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# INTEGRATION HOOK -- vision parse.
#
# If Azure OpenAI is configured we send the uploaded image to a GPT-4o/4.1
# vision deployment with a structured-output prompt and get back {nodes,edges}.
# Otherwise we fall back to a deterministic mock so the stage demo always works.
#
# Auth (in priority order):
#   1. AZURE_OPENAI_API_KEY            -> api-key header
#   2. AZURE_OPENAI_TOKEN              -> Bearer token (AAD)
#   3. az account get-access-token     -> Bearer token, auto-fetched via CLI
#      (used when the resource has local-auth/keys disabled)
#
# Config env:
#   AZURE_OPENAI_ENDPOINT    e.g. https://my-aoai.openai.azure.com
#   AZURE_OPENAI_DEPLOYMENT  vision-capable deployment (default: gpt-4o)
#   AZURE_OPENAI_API_VERSION (default: 2024-08-01-preview)
# ---------------------------------------------------------------------------
# App-centric types (web patterns) + Azure infra types (real cloud diagrams).
NODE_TYPES = [
    "frontend", "api", "worker", "gateway", "gpu",
    "database", "cache", "queue", "storage", "cdn", "staticsite",
    "appgateway", "waf", "apim", "aks", "keyvault", "acr", "appconfig",
    "managedidentity", "vm", "privatedns", "privateendpoint",
]

VISION_SYSTEM = (
    "You convert a software or Azure architecture diagram into a JSON graph. "
    "Return ONLY JSON: {\"id\": <slug>, \"name\": <short title>, "
    "\"nodes\": [{\"id\": <slug>, \"type\": <one of %s>, \"label\": <text>}], "
    "\"edges\": [[<src id>, <dst id>]]}. Infer arrows/lines as edges. "
    "Map each box to the closest type slug: App Gateway->appgateway, WAF->waf, "
    "API Management->apim, AKS/Kubernetes->aks, Key Vault->keyvault, "
    "Container Registry->acr, App Configuration->appconfig, "
    "Managed Identity->managedidentity, Virtual Machine/Jumpbox/Agent->vm, "
    "Private DNS->privatedns, Private Endpoint->privateendpoint, "
    "Client/Browser->frontend." % NODE_TYPES)

_TOKEN_CACHE = {"token": None, "exp": 0}


def _get_aad_token():
    """Fetch an AAD bearer token for Cognitive Services via the az CLI.
    Cached until ~5 min before expiry. Returns None if unavailable."""
    import subprocess
    now = time.time()
    if _TOKEN_CACHE["token"] and _TOKEN_CACHE["exp"] - 300 > now:
        return _TOKEN_CACHE["token"]
    try:
        out = subprocess.run(
            ["az", "account", "get-access-token",
             "--resource", "https://cognitiveservices.azure.com",
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, timeout=30)
        tok = out.stdout.strip()
        if out.returncode == 0 and len(tok) > 50:
            _TOKEN_CACHE["token"] = tok
            _TOKEN_CACHE["exp"] = now + 3000  # ~50 min typical lifetime
            return tok
        print("[vision] az token fetch failed: %s" % (out.stderr.strip()[:200]))
    except Exception as e:
        print("[vision] az token error: %s" % e)
    return None


def _auth_header():
    if os.environ.get("AZURE_OPENAI_API_KEY"):
        return ("api-key", os.environ["AZURE_OPENAI_API_KEY"])
    if os.environ.get("AZURE_OPENAI_TOKEN"):
        return ("Authorization", "Bearer " + os.environ["AZURE_OPENAI_TOKEN"])
    tok = _get_aad_token()
    if tok:
        return ("Authorization", "Bearer " + tok)
    return None


def _azure_vision_configured():
    if not os.environ.get("AZURE_OPENAI_ENDPOINT"):
        return False
    return _auth_header() is not None


def _azure_vision_parse(image_bytes):
    """Call Azure OpenAI vision via stdlib urllib. Returns graph dict."""
    import base64
    import urllib.request

    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    url = "%s/openai/deployments/%s/chat/completions?api-version=%s" % (
        endpoint, deployment, api_version)

    auth = _auth_header()
    if not auth:
        raise RuntimeError("no Azure OpenAI auth available")

    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "messages": [
            {"role": "system", "content": VISION_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": "Parse this architecture diagram."},
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64,%s" % b64}},
            ]},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "max_tokens": 1500,
    }
    headers = {"Content-Type": "application/json", auth[0]: auth[1]}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    graph = json.loads(content)
    graph.setdefault("id", "sketch")
    graph.setdefault("name", "Parsed sketch")
    graph.setdefault("edges", [])
    return graph


def parse_sketch(sample_id=None, image_bytes=None):
    if sample_id and sample_id in SKETCHES:
        return SKETCHES[sample_id]
    if image_bytes:
        if _azure_vision_configured():
            try:
                return _azure_vision_parse(image_bytes)
            except Exception as e:  # never break the demo -- fall back to mock
                print("[vision] Azure call failed, using mock: %s" % e)
        # MOCK: deterministic pick based on image hash so uploads feel "recognized".
        idx = int(hashlib.md5(image_bytes).hexdigest(), 16) % len(SKETCHES)
        return list(SKETCHES.values())[idx]
    return SKETCHES["webapp-basic"]


# ---------------------------------------------------------------------------
# IaC generation -- deterministic template mapping (this part is real logic).
# ---------------------------------------------------------------------------
# Managed Azure resources (rendered as Bicep). Keyed by node type.
BICEP_FOR = {
    "database":   "resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2023-03-01-preview' = {\n  name: 'pg-${appName}'\n  location: location\n  sku: { name: 'Standard_B1ms', tier: 'Burstable' }\n}",
    "cache":      "resource redis 'Microsoft.Cache/redis@2023-08-01' = {\n  name: 'redis-${appName}'\n  location: location\n  properties: { sku: { name: 'Basic', family: 'C', capacity: 0 } }\n}",
    "queue":      "resource sb 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {\n  name: 'sb-${appName}'\n  location: location\n  sku: { name: 'Standard' }\n}",
    "storage":    "resource blob 'Microsoft.Storage/storageAccounts@2023-01-01' = {\n  name: 'st${appName}'\n  location: location\n  sku: { name: 'Standard_LRS' }\n  kind: 'StorageV2'\n}",
    "cdn":        "resource fd 'Microsoft.Cdn/profiles@2023-05-01' = {\n  name: 'fd-${appName}'\n  location: 'global'\n  sku: { name: 'Standard_AzureFrontDoor' }\n}",
    "staticsite": "resource swa 'Microsoft.Web/staticSites@2023-01-01' = {\n  name: 'swa-${appName}'\n  location: location\n  sku: { name: 'Standard', tier: 'Standard' }\n}",
}
# Workloads rendered as Kubernetes Deployments+Services (containerized).
K8S_KINDS = {"frontend", "api", "worker", "gateway", "gpu"}
# Types that receive public traffic and therefore get an Ingress route.
INGRESS_KINDS = {"frontend", "gateway"}
# GPU workloads get a node selector + resource request.
GPU_KINDS = {"gpu"}


def _deployment(node):
    is_gpu = node["type"] in GPU_KINDS
    gpu_resources = (
        "\n        resources:\n          limits: { nvidia.com/gpu: 1 }"
        if is_gpu else "")
    node_selector = (
        "\n      nodeSelector: { accelerator: nvidia }" if is_gpu else "")
    return (
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: %s\n"
        "  labels: { app: %s }\nspec:\n  replicas: 1\n"
        "  selector: { matchLabels: { app: %s } }\n  template:\n"
        "    metadata: { labels: { app: %s } }\n    spec:%s\n      containers:\n"
        "      - name: %s\n        image: ghcr.io/your-org/%s:latest\n"
        "        ports: [ { containerPort: 8080 } ]%s%s"
        % (node["id"], node["id"], node["id"], node["id"], node_selector,
           node["id"], node["id"], _env_block(node), gpu_resources))


# Edge-based networking: each service gets env vars pointing at its downstream
# dependencies (derived from graph edges), so the wiring is real, not implied.
_DOWNSTREAM = {}


def _env_block(node):
    deps = _DOWNSTREAM.get(node["id"], [])
    if not deps:
        return ""
    lines = ["\n        env:"]
    for dep_id, dep_type in deps:
        host = _service_host(dep_id, dep_type)
        lines.append("        - name: %s_URL\n          value: %s"
                     % (dep_id.upper(), host))
    return "\n".join(lines)


def _service_host(node_id, node_type):
    # Managed resources resolve to their Azure endpoint; in-cluster services
    # resolve to their K8s DNS name.
    managed = {
        "database": "pg-${appName}.postgres.database.azure.com",
        "cache":    "redis-${appName}.redis.cache.windows.net",
        "queue":    "sb-${appName}.servicebus.windows.net",
        "storage":  "st${appName}.blob.core.windows.net",
        "cdn":      "fd-${appName}.azurefd.net",
        "staticsite": "swa-${appName}.azurestaticapps.net",
    }
    if node_type in managed:
        return managed[node_type]
    return "http://%s.default.svc.cluster.local:8080" % node_id


def _service(node):
    return (
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: %s\nspec:\n"
        "  selector: { app: %s }\n  ports: [ { port: 8080, targetPort: 8080 } ]"
        % (node["id"], node["id"]))


def _ingress(app, targets):
    rules = []
    for t in targets:
        rules.append(
            "  - http:\n      paths:\n      - path: /\n        pathType: Prefix\n"
            "        backend:\n          service:\n            name: %s\n"
            "            port: { number: 8080 }" % t["id"])
    return (
        "apiVersion: networking.k8s.io/v1\nkind: Ingress\nmetadata:\n"
        "  name: %s-ingress\n  annotations:\n"
        "    kubernetes.io/ingress.class: webapprouting.kubernetes.azure.com\n"
        "spec:\n  rules:\n%s" % (app, "\n".join(rules)))


def _network_policy(node, deps):
    # Default-deny + explicit egress to declared downstreams (in-cluster ones).
    in_cluster = [d for d in deps if d[1] in K8S_KINDS]
    if not in_cluster:
        return None
    to = "\n".join(
        "    - to:\n      - podSelector: { matchLabels: { app: %s } }" % d[0]
        for d in in_cluster)
    return (
        "apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n"
        "  name: %s-egress\nspec:\n  podSelector: { matchLabels: { app: %s } }\n"
        "  policyTypes: [ Egress ]\n  egress:\n%s" % (node["id"], node["id"], to))


def generate_iac(graph):
    # Azure infrastructure diagram (App Gateway / APIM / AKS / Key Vault ...)?
    # Route to the dedicated Azure Bicep generator, which emits a single
    # compile-valid template. K8s manifests aren't the right output here.
    if azure_iac.is_azure_infra(graph):
        return {"bicep": azure_iac.generate_azure_bicep(graph),
                "k8s": "", "kind": "azure-infra"}

    app = graph["id"].replace("-", "")
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}

    # Build downstream dependency map from edges (src -> [(dst_id, dst_type)]).
    global _DOWNSTREAM
    _DOWNSTREAM = {}
    for src, dst in graph.get("edges", []):
        if dst in nodes_by_id:
            _DOWNSTREAM.setdefault(src, []).append((dst, nodes_by_id[dst]["type"]))

    # --- Bicep (managed Azure resources) ---
    bicep = ["param appName string = '%s'" % app,
             "param location string = resourceGroup().location", ""]
    seen = set()
    for n in graph["nodes"]:
        b = BICEP_FOR.get(n["type"])
        if b and n["type"] not in seen:
            bicep.append("// %s (%s)" % (n["label"], n["type"]))
            bicep.append(b)
            bicep.append("")
            seen.add(n["type"])

    # --- Kubernetes (workloads + services + networking + ingress) ---
    manifests = []
    ingress_targets = []
    for n in graph["nodes"]:
        if n["type"] not in K8S_KINDS:
            continue
        manifests.append(_deployment(n))
        manifests.append(_service(n))
        deps = _DOWNSTREAM.get(n["id"], [])
        np = _network_policy(n, deps)
        if np:
            manifests.append(np)
        if n["type"] in INGRESS_KINDS:
            ingress_targets.append(n)
    if ingress_targets:
        manifests.append(_ingress(app, ingress_targets))

    return {"bicep": "\n".join(bicep).strip(), "k8s": "\n---\n".join(manifests),
            "kind": "app"}


# ---------------------------------------------------------------------------
# Bicep validation -- compile the generated Bicep to ARM JSON with the Bicep
# CLI. This is a REAL check (not a mock): if it returns ok, the template is
# valid ARM. Used by the deploy step as proof before any actual provisioning.
# ---------------------------------------------------------------------------
def validate_bicep(bicep_text):
    if not bicep_text.strip():
        return {"validated": False, "reason": "no bicep to validate"}
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".bicep", delete=False) as tf:
            tf.write(bicep_text)
            path = tf.name
        out = subprocess.run(["az", "bicep", "build", "--file", path, "--stdout"],
                             capture_output=True, text=True, timeout=120)
        os.unlink(path)
        if out.returncode == 0:
            arm = json.loads(out.stdout)
            n = len(arm.get("resources", []))
            return {"validated": True, "arm_resources": n,
                    "arm_bytes": len(out.stdout)}
        return {"validated": False, "reason": out.stderr.strip()[:800]}
    except FileNotFoundError:
        return {"validated": False, "reason": "bicep CLI not found"}
    except Exception as e:
        return {"validated": False, "reason": str(e)[:400]}


# ---------------------------------------------------------------------------
# INTEGRATION HOOK -- deploy.
# For Azure-infra diagrams we always do a REAL validation: compile the full
# generated Bicep to ARM via the Bicep CLI (proof the whole diagram is
# deployable). Then, if a target RG is configured, we REALLY provision the
# demo-safe subset (Managed Identity + Key Vault + ACR Basic) -- cheap and fast
# enough for a live demo -- while the heavy resources (App Gateway/APIM/AKS)
# stay validate-only because they take many minutes and cost money.
#
# Config:
#   DEPLOY_RG          target resource group for the real safe-subset deploy
#   DEPLOY_MODE        'real' (default when DEPLOY_RG set) provisions the subset;
#                      'whatif' runs a preview of the FULL template instead;
#                      unset/empty -> validate only.
# ---------------------------------------------------------------------------
def deploy(graph):
    iac = generate_iac(graph)
    result = {"resources": len(graph["nodes"])}
    if iac.get("kind") != "azure-infra":
        time.sleep(0.6)
        result["status"] = "running"
        result["url"] = "https://%s.sandbox.example.dev" % graph["id"]
        return result

    # Always validate the full template first.
    val = validate_bicep(iac["bicep"])
    result.update(val)
    result["status"] = "validated" if val.get("validated") else "invalid"
    result["url"] = "https://%s.sandbox.example.dev" % graph["id"]
    if not val.get("validated"):
        return result

    rg = os.environ.get("DEPLOY_RG")
    mode = os.environ.get("DEPLOY_MODE", "real" if rg else "").lower()
    if rg and mode == "whatif":
        result["what_if"] = _what_if(iac["bicep"], rg)
    elif rg and mode == "real" and azure_iac.has_safe_subset(graph):
        result["real_deploy"] = _real_deploy_subset(graph, rg)
        if result["real_deploy"].get("ok"):
            result["status"] = "deployed"
    return result


def _real_deploy_subset(graph, rg):
    """Actually provision the demo-safe subset into `rg`. Returns created
    resource outputs (identity id, key vault uri, ACR login server)."""
    suffix = str(int(time.time()))[-6:]
    bicep = azure_iac.generate_safe_subset_bicep(graph, suffix)
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".bicep", delete=False) as tf:
            tf.write(bicep)
            path = tf.name
        name = "wb-demo-%s" % suffix
        out = subprocess.run(
            ["az", "deployment", "group", "create", "-g", rg, "--name", name,
             "--template-file", path, "--query", "properties.outputs", "-o", "json"],
            capture_output=True, text=True, timeout=300)
        os.unlink(path)
        if out.returncode != 0:
            return {"ok": False, "error": (out.stderr or out.stdout).strip()[:800]}
        outputs = json.loads(out.stdout or "{}")
        flat = {k: v.get("value") for k, v in outputs.items()}
        flat["ok"] = True
        flat["resource_group"] = rg
        flat["deployment"] = name
        return flat
    except Exception as e:
        return {"ok": False, "error": str(e)[:400]}


def _what_if(bicep_text, rg):
    """Optional real preview: az deployment group what-if. Slow; opt-in."""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".bicep", delete=False) as tf:
            tf.write(bicep_text)
            path = tf.name
        out = subprocess.run(
            ["az", "deployment", "group", "what-if", "-g", rg,
             "--template-file", path, "--no-pretty-print"],
            capture_output=True, text=True, timeout=300)
        os.unlink(path)
        return {"ok": out.returncode == 0,
                "output": (out.stdout or out.stderr)[:2000]}
    except Exception as e:
        return {"ok": False, "output": str(e)[:400]}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "static", "index.html"), "rb") as fh:
                return self._send(200, fh.read(), "text/html; charset=utf-8")
        if u.path == "/api/config":
            return self._send(200, json.dumps(
                {"vision": "live" if _azure_vision_configured() else "mock"}))
        if u.path == "/api/samples":
            return self._send(200, json.dumps(
                [{"id": s["id"], "name": s["name"], "sketch_ascii": s["sketch_ascii"]}
                 for s in SKETCHES.values()]))
        if u.path == "/api/parse":
            qs = parse_qs(u.query)
            g = parse_sketch(sample_id=qs.get("sample", [None])[0])
            return self._send(200, json.dumps(g))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        if u.path == "/api/parse-image":
            g = parse_sketch(image_bytes=raw or b"x")
            return self._send(200, json.dumps(g))
        if u.path == "/api/generate":
            graph = json.loads(raw or b"{}")
            return self._send(200, json.dumps(generate_iac(graph)))
        if u.path == "/api/deploy":
            graph = json.loads(raw or b"{}")
            return self._send(200, json.dumps(deploy(graph)))
        return self._send(404, json.dumps({"error": "not found"}))


if __name__ == "__main__":
    print("Whiteboard -> App running -> http://localhost:%d" % PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

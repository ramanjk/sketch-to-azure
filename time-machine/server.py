#!/usr/bin/env python3
"""Time Machine - incident replay & fix agent (hackathon scaffold).

Pure Python stdlib. No external dependencies. Run:  python3 server.py
Then open http://localhost:8011

The "intelligence" here is a deterministic mock so the demo runs with zero
API keys. Swap the marked hook (analyze_incident) for a real Azure AI Foundry
agent + MCP tool calls when you're ready.
"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8011"))

with open(os.path.join(HERE, "incidents.json"), encoding="utf-8") as f:
    INCIDENTS = json.load(f)


# ---------------------------------------------------------------------------
# INTEGRATION HOOK -- replace this mock with a real agent call.
#
# Real version would:
#   1. Use MCP servers (Prometheus/Loki + GitHub + AKS) to pull the timeline.
#   2. Call an Azure AI Foundry agent to reason over the correlated signals.
#   3. Return the same shape this mock returns so the UI is unchanged.
#
# from azure.ai.projects import AIProjectClient  # example
# def analyze_incident(incident_id): ... call agent, return dict ...
# ---------------------------------------------------------------------------
def analyze_incident(incident_id):
    """MOCK: look up a canned, replayable incident."""
    inc = INCIDENTS.get(incident_id.upper().strip())
    if not inc:
        return None
    return inc


def apply_fix_in_sandbox(incident_id):
    """MOCK: pretend to apply the fix to a sandbox namespace and measure
    recovery. Real version would kubectl/helm apply into a sandbox and poll
    Prometheus for the recovered metric series."""
    inc = INCIDENTS.get(incident_id.upper().strip())
    if not inc:
        return None
    return {
        "applied": inc["fix"]["manifest"],
        "pr_title": inc["fix"]["pr_title"],
        "pr_url": "https://github.com/your-org/%s/pull/1337" % inc["service"],
        "metrics": inc["metrics"],
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # quieter console
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/" or u.path == "/index.html":
            with open(os.path.join(HERE, "static", "index.html"), "rb") as fh:
                return self._send(200, fh.read(), "text/html; charset=utf-8")
        if u.path == "/api/incidents":
            return self._send(200, json.dumps(
                [{"id": i["id"], "title": i["title"], "severity": i["severity"]}
                 for i in INCIDENTS.values()]))
        if u.path == "/api/replay":
            qs = parse_qs(u.query)
            inc_id = (qs.get("id", [""])[0])
            inc = analyze_incident(inc_id)
            if not inc:
                return self._send(404, json.dumps({"error": "unknown incident id"}))
            return self._send(200, json.dumps(inc))
        if u.path == "/api/fix":
            qs = parse_qs(u.query)
            inc_id = (qs.get("id", [""])[0])
            res = apply_fix_in_sandbox(inc_id)
            if not res:
                return self._send(404, json.dumps({"error": "unknown incident id"}))
            time.sleep(0.4)  # feel of "applying"
            return self._send(200, json.dumps(res))
        return self._send(404, json.dumps({"error": "not found"}))


if __name__ == "__main__":
    print("Time Machine running -> http://localhost:%d" % PORT)
    print("Try incidents: %s" % ", ".join(INCIDENTS.keys()))
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

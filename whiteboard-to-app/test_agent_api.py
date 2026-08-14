import base64
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import server


GRAPH = {
    "id": "azure-demo",
    "name": "Azure demo",
    "nodes": [
        {"id": "identity", "type": "managedidentity", "label": "Identity"},
        {"id": "vault", "type": "keyvault", "label": "Key Vault"},
    ],
    "edges": [["identity", "vault"]],
}

GENERIC_GRAPH = {
    "id": "serverless-app",
    "name": "Serverless application",
    "nodes": [
        {
            "id": "orders-function",
            "type": "azure",
            "label": "Orders Function",
            "properties": {
                "service": "Azure Functions",
                "resourceType": "Microsoft.Web/sites",
            },
        },
        {
            "id": "orders-db",
            "type": "azure",
            "label": "Orders Cosmos DB",
            "properties": {
                "service": "Azure Cosmos DB",
                "resourceType": "Microsoft.DocumentDB/databaseAccounts",
            },
        },
    ],
    "edges": [["orders-function", "orders-db"]],
}

SIGNED_IAC = {
    "bicep": (
        "param location string = resourceGroup().location\n"
        "resource identity 'Microsoft.ManagedIdentity/"
        "userAssignedIdentities@2023-01-31' = {\n"
        "  name: 'signed-plan-id'\n"
        "  location: location\n"
        "}"
    ),
    "k8s": "",
    "kind": "azure-infra",
    "warnings": ["Signed warning"],
    "unsupported": [],
}


class AgentApiTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "AGENT_API_KEY": "test-api-key",
            "AGENT_PLAN_SIGNING_KEY": "test-signing-key",
            "DEPLOY_RG": "test-rg",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_validates_and_normalizes_graph(self):
        self.assertEqual(server._validate_graph(GRAPH), GRAPH)

    def test_rejects_graph_with_unknown_edge(self):
        graph = dict(GRAPH, edges=[["identity", "missing"]])
        with self.assertRaisesRegex(ValueError, "existing node ids"):
            server._validate_graph(graph)

    def test_preserves_generic_azure_service_metadata(self):
        self.assertEqual(server._validate_graph(GENERIC_GRAPH), GENERIC_GRAPH)

    def test_normalizes_multiple_aks_icons_into_one_cluster_and_workloads(self):
        graph = {
            "id": "aks-app",
            "name": "Application deployment to AKS",
            "nodes": [
                {"id": "front-image", "type": "azure", "label": "Front Image",
                 "properties": {"service": "Container Image"}},
                {"id": "app-image", "type": "azure", "label": "App Image",
                 "properties": {"service": "Container Image"}},
                {"id": "db-image", "type": "azure", "label": "DB Image",
                 "properties": {"service": "Container Image"}},
                {"id": "front", "type": "aks", "label": "Front End"},
                {"id": "app", "type": "aks", "label": "App"},
                {"id": "db", "type": "aks", "label": "DB"},
            ],
            "edges": [],
        }
        normalized = server._normalize_vision_graph(graph)
        counts = {
            kind: sum(node["type"] == kind for node in normalized["nodes"])
            for kind in ("aks", "k8sworkload", "containerimage")
        }
        self.assertEqual(
            counts, {"aks": 1, "k8sworkload": 3, "containerimage": 3})

    def test_generic_azure_graph_uses_extensible_generator(self):
        with patch.object(
                server, "_generic_azure_bicep",
                return_value=SIGNED_IAC) as generic:
            self.assertEqual(server.generate_iac(GENERIC_GRAPH), SIGNED_IAC)
        generic.assert_called_once_with(GENERIC_GRAPH)

    def test_decodes_supported_image(self):
        body = {
            "contentType": "image/png",
            "imageBase64": base64.b64encode(b"png-data").decode("ascii"),
        }
        self.assertEqual(
            server._decode_agent_image(body), (b"png-data", "image/png"))

    def test_rejects_invalid_image_encoding(self):
        with self.assertRaisesRegex(ValueError, "valid base64"):
            server._decode_agent_image({
                "contentType": "image/png",
                "imageBase64": "not base64!",
            })

    def test_signed_plan_round_trip_and_tamper_rejection(self):
        token = server._create_plan_token(GRAPH)
        self.assertEqual(server._verify_plan_token(token), GRAPH)
        with self.assertRaisesRegex(ValueError, "signature"):
            server._verify_plan_token(token[:-1] + ("A" if token[-1] != "A" else "B"))

    def test_expired_plan_is_rejected(self):
        with patch.object(server.time, "time", return_value=time.time() - 90000):
            token = server._create_plan_token(GRAPH)
        with self.assertRaisesRegex(ValueError, "expired"):
            server._verify_plan_token(token)

    def test_preview_uses_exact_signed_bicep(self):
        token = server._create_plan_token(GRAPH, SIGNED_IAC)
        with patch.object(
                server, "validate_bicep",
                return_value={"validated": True}), patch.object(
                server, "_what_if",
                return_value={"ok": True, "output": "preview"}) as what_if:
            result = server.preview_agent_plan({"planToken": token})
        self.assertTrue(result["whatIf"]["ok"])
        what_if.assert_called_once_with(
            SIGNED_IAC["bicep"], os.environ.get("DEPLOY_RG"))

    def test_generic_generation_repairs_compiler_failure(self):
        invalid = {
            "bicep": "invalid",
            "assumptions": [],
            "unsupported": [],
        }
        valid = {
            "bicep": SIGNED_IAC["bicep"],
            "assumptions": ["Added a hosting plan"],
            "unsupported": [],
        }
        with patch.object(
                server, "_azure_vision_configured",
                return_value=True), patch.object(
                server, "_azure_json_completion",
                side_effect=[invalid, valid]), patch.object(
                server, "validate_bicep",
                side_effect=[
                    {"validated": False, "reason": "compiler error"},
                    {"validated": True},
                ]), patch.object(
                server, "_what_if",
                return_value={"ok": True, "output": "preview"}):
            result = server._generic_azure_bicep(GENERIC_GRAPH)
        self.assertEqual(result["generationAttempts"], 2)
        self.assertEqual(result["warnings"], ["Added a hosting plan"])

    def test_generic_generation_reports_environment_blocker(self):
        generated = {
            "bicep": SIGNED_IAC["bicep"],
            "assumptions": [],
            "unsupported": [],
        }
        with patch.object(
                server, "_azure_vision_configured",
                return_value=True), patch.object(
                server, "_azure_json_completion",
                return_value=generated), patch.object(
                server, "validate_bicep",
                return_value={"validated": True}), patch.object(
                server, "_what_if",
                return_value={
                    "ok": False,
                    "output": "InternalSubscriptionIsOverQuotaForSku - quota exceeded",
                }):
            result = server._generic_azure_bicep(GENERIC_GRAPH)
        self.assertTrue(result["preflightBlocked"])
        self.assertIn("environment blocker", result["warnings"][-1])

    def test_generic_generation_returns_compile_valid_plan_when_preflight_remains_invalid(self):
        generated = {
            "bicep": SIGNED_IAC["bicep"],
            "assumptions": [],
            "unsupported": [],
        }
        with patch.dict(os.environ, {
                "GENERIC_IAC_MAX_ATTEMPTS": "1"}), patch.object(
                server, "_azure_vision_configured",
                return_value=True), patch.object(
                server, "_azure_json_completion",
                return_value=generated), patch.object(
                server, "validate_bicep",
                return_value={"validated": True}), patch.object(
                server, "_what_if",
                return_value={
                    "ok": False,
                    "output": "InvalidResourceReference - backend missing",
                }):
            result = server._generic_azure_bicep(GENERIC_GRAPH)
        self.assertTrue(result["preflightFailed"])
        self.assertIn("preflight still fails", result["warnings"][-1])

    def test_only_graph_resources_are_marked_unsupported(self):
        unsupported, limitations = server._partition_unsupported(
            GENERIC_GRAPH,
            [
                "Orders Cosmos DB cannot be represented",
                "RBAC role assignments require more permissions",
            ])
        self.assertEqual(unsupported, ["Orders Cosmos DB cannot be represented"])
        self.assertEqual(
            limitations, ["RBAC role assignments require more permissions"])

    def test_deploy_requires_approval(self):
        with self.assertRaisesRegex(PermissionError, "explicit approval"):
            server.deploy_agent_plan({"approved": False})

    def test_ui_displays_manifests_for_azure_infrastructure(self):
        html = Path(server.HERE, "static", "index.html").read_text(
            encoding="utf-8")
        self.assertIn("if(iac.k8s)", html)
        self.assertIn("Download YAML", html)
        self.assertNotIn(
            "if(isAzure){\n    document.getElementById('k8sCard')"
            ".classList.add('hide')",
            html)


if __name__ == "__main__":
    unittest.main()

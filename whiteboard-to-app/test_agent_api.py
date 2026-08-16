import base64
import io
import os
import time
import unittest
import zipfile
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


def vsdx_bytes(unsafe=False):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        if unsafe:
            archive.writestr("../unsafe.xml", "<x/>")
        archive.writestr(
            "visio/pages/pages.xml",
            '<Pages xmlns="http://schemas.microsoft.com/office/visio/2012/main"/>')
        archive.writestr(
            "visio/pages/page1.xml",
            """<PageContents xmlns="http://schemas.microsoft.com/office/visio/2012/main">
              <Shapes>
                <Shape ID="1" NameU="Azure Functions">
                  <Cell N="PinX" V="2"/><Cell N="PinY" V="3"/>
                  <Cell N="Width" V="1"/><Cell N="Height" V="1"/>
                  <Text>Orders Function</Text>
                </Shape>
                <Shape ID="2" NameU="Cosmos DB">
                  <Cell N="PinX" V="5"/><Cell N="PinY" V="3"/>
                  <Text>Orders Database</Text>
                </Shape>
              </Shapes>
              <Connects>
                <Connect FromSheet="1" ToSheet="2" FromCell="EndX" ToCell="PinX"/>
              </Connects>
            </PageContents>""")
    return stream.getvalue()


def svg_bytes(unsafe=False):
    declaration = (
        '<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        if unsafe else "")
    return (declaration + """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <g id="aro" transform="translate(10,-20)">
          <title>Azure Red Hat OpenShift</title>
          <desc>ARO worker nodes with IBM Maximo Application Suite</desc>
          <text>ARO worker nodes</text>
        </g>
        <g id="connector" transform="translate(5,6)">
          <title>Dynamic connector.1</title>
          <path d="M0 0 L10 10"/>
        </g>
      </svg>
    """).encode()


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

    def test_generic_graph_skips_vm_topology_warnings(self):
        with patch.object(
                server.azure_iac, "topology_warnings") as topology_warnings:
            self.assertEqual(server._topology_warnings(GENERIC_GRAPH), [])
        topology_warnings.assert_not_called()

    def test_selects_reference_patterns_from_detected_services(self):
        selected = server._select_reference_patterns(GENERIC_GRAPH)
        self.assertEqual(
            [pattern["id"] for pattern in selected],
            ["serverless-static-functions-cosmos"])

    def test_reference_guidance_is_advisory(self):
        context = server._reference_context(GENERIC_GRAPH)
        self.assertIn("serverless-static-functions-cosmos", context)
        self.assertIn("never add a resource", context)
        self.assertIn(
            "https://github.com/Harshil-kumar-4/3-Tier-Application-Azure",
            context)

    def test_selects_maximo_aro_reference(self):
        graph = {
            "id": "maximo",
            "name": "IBM Maximo on Azure Red Hat OpenShift",
            "nodes": [],
            "edges": [],
        }
        self.assertEqual(
            server._select_reference_patterns(graph)[0]["id"],
            "ibm-maximo-aro")

    def test_decodes_supported_image(self):
        body = {
            "contentType": "image/png",
            "imageBase64": base64.b64encode(b"png-data").decode("ascii"),
        }
        self.assertEqual(
            server._decode_agent_image(body), (b"png-data", "image/png"))

    def test_decodes_visio_file(self):
        content = vsdx_bytes()
        body = {
            "contentType": server.VSDX_MEDIA_TYPE,
            "imageBase64": base64.b64encode(content).decode("ascii"),
        }
        self.assertEqual(
            server._decode_agent_file(body),
            (content, server.VSDX_MEDIA_TYPE))

    def test_detects_svg_with_misleading_png_type(self):
        content = svg_bytes()
        body = {
            "contentType": "image/png",
            "imageBase64": base64.b64encode(content).decode("ascii"),
        }
        self.assertEqual(
            server._decode_agent_file(body),
            (content, server.SVG_MEDIA_TYPE))

    def test_extracts_svg_shapes_and_connectors(self):
        structure = server._extract_svg_structure(svg_bytes())
        self.assertEqual(
            structure["shapes"][0]["label"],
            "ARO worker nodes with IBM Maximo Application Suite")
        self.assertEqual(structure["shapes"][0]["x"], 10.0)
        self.assertEqual(structure["shapes"][0]["y"], -20.0)
        self.assertEqual(structure["connectors"][0]["path"], "M0 0 L10 10")

    def test_rejects_unsafe_svg_xml(self):
        with self.assertRaisesRegex(ValueError, "declarations"):
            server._extract_svg_structure(svg_bytes(unsafe=True))

    def test_svg_parse_uses_structured_completion(self):
        with patch.object(
                server, "_azure_json_completion",
                return_value=GENERIC_GRAPH) as completion:
            graph = server._azure_svg_parse(svg_bytes())
        self.assertEqual(graph, GENERIC_GRAPH)
        prompt = completion.call_args.args[0][1]["content"]
        self.assertIn("IBM Maximo Application Suite", prompt)
        self.assertIn("M0 0 L10 10", prompt)

    def test_live_parse_does_not_fall_back_to_mock(self):
        with patch.object(
                server, "_azure_vision_configured",
                return_value=True), patch.object(
                server, "_azure_vision_parse",
                side_effect=RuntimeError("vision failed")):
            with self.assertRaisesRegex(RuntimeError, "vision failed"):
                server.parse_sketch(image_bytes=b"invalid image")

    def test_extracts_visio_shapes_and_connectors(self):
        structure = server._extract_vsdx_structure(vsdx_bytes())
        page = structure["pages"][0]
        self.assertEqual(
            [shape["text"] for shape in page["shapes"]],
            ["Orders Function", "Orders Database"])
        self.assertEqual(
            page["connectors"][0]["from"], "1")
        self.assertEqual(
            page["connectors"][0]["to"], "2")

    def test_rejects_unsafe_visio_package(self):
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            server._extract_vsdx_structure(vsdx_bytes(unsafe=True))

    def test_visio_parse_uses_structured_completion(self):
        with patch.object(
                server, "_azure_json_completion",
                return_value=GENERIC_GRAPH) as completion:
            graph = server._azure_vsdx_parse(vsdx_bytes())
        self.assertEqual(graph, GENERIC_GRAPH)
        prompt = completion.call_args.args[0][1]["content"]
        self.assertIn("Orders Function", prompt)
        self.assertIn('"from":"1"', prompt)

    def test_rejects_invalid_image_encoding(self):
        with self.assertRaisesRegex(ValueError, "valid base64"):
            server._decode_agent_image({
                "contentType": "image/png",
                "imageBase64": "not base64!",
            })

    def test_signed_plan_round_trip_and_tamper_rejection(self):
        token = server._create_plan_token(GRAPH)
        self.assertEqual(server._verify_plan_token(token), GRAPH)
        payload, signature = token.split(".", 1)
        tampered = payload + "." + (
            "A" if signature[0] != "A" else "B") + signature[1:]
        with self.assertRaisesRegex(ValueError, "signature"):
            server._verify_plan_token(tampered)

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

    def test_compiler_diagnostics_prioritize_errors(self):
        stderr = "\n".join(
            ["file.bicep(1,1) : Warning sample"] * 100
            + ["file.bicep(8,2) : Error BCP123: actionable failure"]
        )
        diagnostics = server._compiler_diagnostics(stderr)
        self.assertEqual(
            diagnostics,
            "file.bicep(8,2) : Error BCP123: actionable failure")

    def test_aro_semantic_validation_requires_cluster_profiles(self):
        arm = {
            "resources": [{
                "type": "Microsoft.RedHatOpenShift/openShiftClusters",
                "properties": {
                    "clusterProfile": {
                        "pullSecret": "[parameters('aroPullSecret')]",
                        "resourceGroupId": "[resourceGroup().id]",
                    },
                    "masterProfile": {"subnetId": "master"},
                    "workerProfiles": [{"name": "worker"}],
                    "servicePrincipalProfile": {
                        "clientId": "[parameters('aroClientId')]",
                        "clientSecret": "[parameters('aroClientSecret')]",
                    },
                },
            }],
        }
        violations = server._arm_semantic_violations(arm)
        self.assertIn("ARO clusterProfile.version is required", violations)
        self.assertIn("ARO masterProfile.vmSize is required", violations)
        self.assertIn(
            "ARO workerProfiles[0].diskSizeGB is required", violations)
        self.assertIn(
            "ARO clusterProfile.resourceGroupId must be a distinct "
            "managed resource group",
            violations)

    def test_generated_bicep_removes_multiline_trailing_commas(self):
        source = "var items = [\n  {\n    name: 'one',\n  },\n]\n"
        self.assertEqual(
            server._normalize_generated_bicep(source),
            "var items = [\n  {\n    name: 'one'\n  }\n]")

    def test_bicep_preserves_manual_components_as_comments(self):
        bicep = server._bicep_with_manual_actions(
            "param location string = resourceGroup().location",
            ["Register Microsoft.RedHatOpenShift"],
            ["twilio-sendgrid"],
        )
        self.assertIn("// PRE-DEPLOYMENT MANUAL ACTIONS", bicep)
        self.assertIn("Register Microsoft.RedHatOpenShift", bicep)
        self.assertIn(
            "Complete external or manual component: twilio-sendgrid", bicep)

    def test_detects_hard_coded_bicep_secrets(self):
        bicep = (
            "resource sql 'Microsoft.Sql/managedInstances@2023-08-01' = {\n"
            "  properties: {\n"
            "    administratorLoginPassword: 'ChangeMe123!'\n"
            "  }\n"
            "}\n"
        )
        self.assertEqual(
            server._bicep_secret_violations(bicep),
            ["administratorLoginPassword: 'ChangeMe123!'"])
        self.assertEqual(
            server._bicep_secret_violations(
                "@secure()\nparam adminPassword string = newGuid()\n"),
            [])

    def test_detects_missing_deployable_graph_resources(self):
        graph = {
            "id": "aro-files",
            "name": "ARO with Azure Files",
            "nodes": [
                {"id": "aro", "type": "azure",
                 "label": "Azure Red Hat OpenShift"},
                {"id": "files", "type": "azure",
                 "label": "Azure Files Premium"},
            ],
            "edges": [],
        }
        violations = server._graph_resource_coverage_violations(
            graph,
            {"resource_type_counts": {
                "Microsoft.RedHatOpenShift/openShiftClusters": 1,
            }})
        self.assertEqual(
            violations,
            ["Azure Files share requires 1 Bicep resource(s), but 0 were generated"])

    def test_generic_generation_retries_timeout(self):
        generated = {
            "bicep": SIGNED_IAC["bicep"],
            "assumptions": [],
            "unsupported": [],
        }
        with patch.object(
                server, "_azure_vision_configured",
                return_value=True), patch.object(
                server, "_azure_json_completion",
                side_effect=[TimeoutError(), generated]), patch.object(
                server, "validate_bicep",
                return_value={"validated": True}), patch.object(
                server, "_what_if",
                return_value={"ok": True, "output": "preview"}):
            result = server._generic_azure_bicep(GENERIC_GRAPH)
        self.assertEqual(result["generationAttempts"], 2)

    def test_generic_generation_returns_required_parameters(self):
        generated = {
            "bicep": (
                "@secure()\n"
                "param pullSecret string\n"
                "param aroVersion string\n"
                "resource identity 'Microsoft.ManagedIdentity/"
                "userAssignedIdentities@2023-01-31' = {\n"
                "  name: 'aro-id'\n"
                "  location: resourceGroup().location\n"
                "}"
            ),
            "assumptions": [],
            "unsupported": [],
        }
        validation = {
            "validated": True,
            "required_parameters": ["pullSecret", "aroVersion"],
            "required_parameter_details": [
                {"name": "pullSecret", "type": "secureString"},
                {"name": "aroVersion", "type": "string"},
            ],
        }
        with patch.object(
                server, "_azure_vision_configured",
                return_value=True), patch.object(
                server, "_azure_json_completion",
                return_value=generated), patch.object(
                server, "validate_bicep",
                return_value=validation):
            result = server._generic_azure_bicep(GENERIC_GRAPH)
        self.assertTrue(result["requiresParameters"])
        self.assertEqual(
            result["requiredParameters"], ["pullSecret", "aroVersion"])
        self.assertIn(
            "Provide deployment values for required parameters",
            result["manualActions"][-1])
        self.assertIn(
            "// PRE-DEPLOYMENT MANUAL ACTIONS", result["bicep"])

    def test_preview_does_not_run_without_required_parameters(self):
        token = server._create_plan_token(GRAPH, SIGNED_IAC)
        with patch.object(
                server, "validate_bicep",
                return_value={
                    "validated": True,
                    "required_parameters": ["aroVersion"],
                }), patch.object(server, "_what_if") as what_if:
            result = server.preview_agent_plan({"planToken": token})
        self.assertFalse(result["whatIf"]["ok"])
        self.assertIn("aroVersion", result["whatIf"]["output"])
        what_if.assert_not_called()

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

    def test_sku_capacity_is_an_environment_blocker(self):
        self.assertTrue(server._preflight_environment_blocker(
            "SkuNotAvailable - failed for Capacity Restrictions"))

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
        self.assertIn("Pre-deployment actions:", html)
        self.assertIn("Provide required inputs before deploy", html)
        self.assertNotIn(
            "if(isAzure){\n    document.getElementById('k8sCard')"
            ".classList.add('hide')",
            html)


if __name__ == "__main__":
    unittest.main()

import json
import shutil
import subprocess
import tempfile
import unittest

import azure_iac
import server


def node(node_id, node_type, label, **properties):
    value = {"id": node_id, "type": node_type, "label": label}
    if properties:
        value["properties"] = properties
    return value


def three_tier_graph():
    return {
        "id": "three-tier-azure",
        "name": "Three-tier Azure application",
        "nodes": [
            node("demo-vnet", "vnet", "eb-demo-vnet",
                 addressPrefix="10.0.0.0/20"),
            node("web-subnet", "subnet", "eb-demo-subnet-web",
                 parent="demo-vnet", addressPrefix="10.0.1.0/25", role="web"),
            node("app-subnet", "subnet", "eb-demo-subnet-app",
                 parent="demo-vnet", addressPrefix="10.0.3.0/25", role="app"),
            node("db-subnet", "subnet", "eb-demo-subnet-db",
                 parent="demo-vnet", addressPrefix="10.0.5.0/25", role="database"),
            node("web-nsg", "nsg", "web-nsg", parent="web-subnet"),
            node("app-nsg", "nsg", "app-nsg", parent="app-subnet"),
            node("db-nsg", "nsg", "db-nsg", parent="db-subnet"),
            node("web-lb", "loadbalancer", "web-lb", parent="demo-vnet",
                 access="public", role="web", port=80),
            node("app-ilb", "loadbalancer", "app-ilb", parent="demo-vnet",
                 access="internal", role="app", port=8080),
            node("web-vm-1", "vm", "web-vm-1", parent="web-subnet", role="web"),
            node("web-vm-2", "vm", "web-vm-2", parent="web-subnet", role="web"),
            node("app-vm-1", "vm", "app-vm-1", parent="app-subnet", role="app"),
            node("app-vm-2", "vm", "app-vm-2", parent="app-subnet", role="app"),
            node("db-vm", "vm", "db-vm", parent="db-subnet",
                 role="database", engine="mysql"),
            node("jump-vm", "vm", "Jump vm", parent="demo-vnet",
                 role="jumpbox"),
        ],
        "edges": [
            ["web-lb", "web-vm-1"],
            ["web-lb", "web-vm-2"],
            ["web-vm-1", "app-ilb"],
            ["web-vm-2", "app-ilb"],
            ["app-ilb", "app-vm-1"],
            ["app-ilb", "app-vm-2"],
            ["app-vm-1", "db-vm"],
            ["app-vm-2", "db-vm"],
            ["jump-vm", "web-vm-1"],
            ["jump-vm", "web-vm-2"],
            ["jump-vm", "app-vm-1"],
            ["jump-vm", "app-vm-2"],
            ["jump-vm", "db-vm"],
        ],
    }


def two_tier_graph():
    return {
        "id": "two-tier-web",
        "name": "Two-tier web application",
        "nodes": [
            node("app-vnet", "vnet", "Application VNet",
                 addressPrefix="10.20.0.0/16"),
            node("web-subnet", "subnet", "Web subnet", parent="app-vnet",
                 addressPrefix="10.20.1.0/24", role="web"),
            node("data-subnet", "subnet", "Data subnet", parent="app-vnet",
                 addressPrefix="10.20.2.0/24", role="database"),
            node("web-nsg", "nsg", "Web NSG", parent="web-subnet"),
            node("data-nsg", "nsg", "Data NSG", parent="data-subnet"),
            node("public-lb", "loadbalancer", "Public load balancer",
                 parent="web-subnet", access="public", role="web", port=80),
            node("web-1", "vm", "Web VM 1", parent="web-subnet", role="web"),
            node("web-2", "vm", "Web VM 2", parent="web-subnet", role="web"),
            node("data-1", "vm", "Database VM", parent="data-subnet",
                 role="database", engine="postgresql"),
        ],
        "edges": [
            ["public-lb", "web-1"],
            ["public-lb", "web-2"],
            ["web-1", "data-1"],
            ["web-2", "data-1"],
        ],
    }


def private_app_graph():
    return {
        "id": "private-app",
        "name": "Private application tier",
        "nodes": [
            node("corp-vnet", "vnet", "Corporate VNet",
                 addressPrefix="10.40.0.0/16"),
            node("jump-subnet", "subnet", "Management subnet",
                 parent="corp-vnet", addressPrefix="10.40.1.0/24",
                 role="jumpbox"),
            node("app-subnet", "subnet", "Application subnet",
                 parent="corp-vnet", addressPrefix="10.40.2.0/24", role="app"),
            node("jump-nsg", "nsg", "Management NSG", parent="jump-subnet"),
            node("app-nsg", "nsg", "Application NSG", parent="app-subnet"),
            node("app-ilb", "loadbalancer", "Internal load balancer",
                 parent="app-subnet", access="internal", role="app", port=8080),
            node("jump-vm", "vm", "Jump VM", parent="jump-subnet",
                 role="jumpbox"),
            node("app-1", "vm", "App VM 1", parent="app-subnet", role="app"),
            node("app-2", "vm", "App VM 2", parent="app-subnet", role="app"),
        ],
        "edges": [
            ["jump-vm", "app-1"],
            ["jump-vm", "app-2"],
            ["app-ilb", "app-1"],
            ["app-ilb", "app-2"],
        ],
    }


def aks_application_graph():
    return {
        "id": "three-tier-aks",
        "name": "Three-tier application on AKS",
        "nodes": [
            node("dockerfiles", "artifact", "Dockerfiles"),
            node("frontend-image", "containerimage", "Frontend image",
                 role="web"),
            node("app-image", "containerimage", "App image", role="app"),
            node("db-image", "containerimage", "DB image", role="database"),
            node("acr", "acr", "Azure Container Registry"),
            node("public-lb", "loadbalancer", "Public load balancer"),
            node("aks", "aks", "Azure Kubernetes Service"),
            node("frontend", "k8sworkload", "Frontend workload",
                 parent="aks", role="web"),
            node("app", "k8sworkload", "App workload",
                 parent="aks", role="app"),
            node("db", "k8sworkload", "DB workload",
                 parent="aks", role="database"),
        ],
        "edges": [
            ["frontend-image", "acr"],
            ["app-image", "acr"],
            ["db-image", "acr"],
            ["acr", "aks"],
            ["aks", "frontend"],
            ["aks", "app"],
            ["aks", "db"],
        ],
    }


@unittest.skipUnless(shutil.which("az"), "Azure CLI is required")
class AzureIacQualityTests(unittest.TestCase):
    def compile_bicep(self, bicep):
        with tempfile.NamedTemporaryFile("w", suffix=".bicep") as stream:
            stream.write(bicep)
            stream.flush()
            result = subprocess.run(
                ["az", "bicep", "build", "--file", stream.name, "--stdout"],
                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def compile(self, graph):
        bicep = azure_iac.generate_azure_bicep(graph)
        return bicep, self.compile_bicep(bicep)

    def test_three_tier_design_preserves_resource_instances(self):
        bicep, arm = self.compile(three_tier_graph())
        types = [resource["type"] for resource in arm["resources"]]
        self.assertEqual(types.count("Microsoft.Compute/virtualMachines"), 6)
        self.assertEqual(types.count("Microsoft.Network/networkInterfaces"), 6)
        self.assertEqual(types.count("Microsoft.Network/loadBalancers"), 2)
        self.assertEqual(types.count("Microsoft.Network/networkSecurityGroups"), 4)
        self.assertIn("10.0.1.0/25", bicep)
        self.assertIn("10.0.3.0/25", bicep)
        self.assertIn("10.0.5.0/25", bicep)
        self.assertIn("10.0.15.224/27", bicep)
        self.assertIn("workload: 'mysql'", bicep)
        self.assertEqual(len(azure_iac.topology_warnings(three_tier_graph())), 3)

    def test_two_tier_design_compiles(self):
        _, arm = self.compile(two_tier_graph())
        types = [resource["type"] for resource in arm["resources"]]
        self.assertEqual(types.count("Microsoft.Compute/virtualMachines"), 3)
        self.assertEqual(types.count("Microsoft.Network/loadBalancers"), 1)

    def test_private_application_design_compiles(self):
        bicep, arm = self.compile(private_app_graph())
        types = [resource["type"] for resource in arm["resources"]]
        self.assertEqual(types.count("Microsoft.Compute/virtualMachines"), 3)
        self.assertEqual(types.count("Microsoft.Network/publicIPAddresses"), 0)
        self.assertIn("privateIPAllocationMethod: 'Dynamic'", bicep)

    def test_incomplete_topology_is_rejected(self):
        graph = three_tier_graph()
        graph["nodes"] = [
            item for item in graph["nodes"] if item["id"] != "app-subnet"
        ]
        with self.assertRaisesRegex(ValueError, "subnet parent"):
            azure_iac.generate_azure_bicep(graph)

    def test_aks_application_uses_one_cluster_and_three_workloads(self):
        iac = server.generate_iac(aks_application_graph())
        arm = self.compile_bicep(iac["bicep"])
        types = [resource["type"] for resource in arm["resources"]]
        self.assertEqual(
            types.count("Microsoft.ContainerService/managedClusters"), 1)
        self.assertEqual(
            types.count("Microsoft.ContainerRegistry/registries"), 1)
        self.assertEqual(iac["k8s"].count("kind: Deployment"), 3)
        self.assertEqual(iac["k8s"].count("kind: Service"), 3)
        self.assertEqual(iac["k8s"].count("type: LoadBalancer"), 1)
        self.assertIn("${ACR_LOGIN_SERVER}/frontend:latest", iac["k8s"])
        self.assertIn("${ACR_LOGIN_SERVER}/app:latest", iac["k8s"])
        self.assertIn("${ACR_LOGIN_SERVER}/db:latest", iac["k8s"])


if __name__ == "__main__":
    unittest.main()

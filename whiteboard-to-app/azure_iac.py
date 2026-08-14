"""Azure-infra Bicep generation for the Whiteboard -> App hack.

Given a parsed graph whose nodes use Azure service types (as returned by the
GPT-4o vision parser on a real Azure architecture diagram), emit a single,
**compile-valid** Bicep template. "Compile-valid" means `bicep build` succeeds
-- every block below was verified against Bicep CLI 0.45.

The app-centric generator in server.py handles the simpler web-app patterns;
this module kicks in when the diagram is an Azure infrastructure diagram.
"""
import ipaddress
import re

# Azure service node types this generator understands.
AZURE_TYPES = {
    "appgateway", "waf", "apim", "aks", "keyvault", "acr", "appconfig",
    "managedidentity", "vm", "privatedns", "privateendpoint",
    "vnet", "subnet", "nsg", "loadbalancer", "azure",
    "artifact", "containerimage", "k8sworkload",
}
# Types that require a VNet + subnets to be emitted.
_NEEDS_VNET = {"appgateway", "vm", "privateendpoint"}
# Fixed subnet order so index references stay stable.
_SUBNETS = ["appgw", "pe", "vm"]


def is_azure_infra(graph):
    return any(n.get("type") in AZURE_TYPES for n in graph.get("nodes", []))


def _present(graph):
    return {n["type"] for n in graph.get("nodes", [])}


def _props(node):
    return node.get("properties", {})


def _symbol(value):
    symbol = re.sub(r"[^a-zA-Z0-9_]", "_", value)
    return symbol if not symbol[:1].isdigit() else "r_" + symbol


def _bicep_string(value):
    return value.replace("'", "''")


def _role(node):
    explicit = _props(node).get("role", "").lower()
    if explicit:
        return explicit
    value = ("%s %s" % (node.get("id", ""), node.get("label", ""))).lower()
    if "jump" in value or "bastion" in value:
        return "jumpbox"
    if "db" in value or "database" in value or "mysql" in value or "sql" in value:
        return "database"
    if "app" in value:
        return "app"
    if "web" in value:
        return "web"
    return "workload"


def _network_topology_nodes(graph):
    types = {"vnet", "subnet", "nsg", "loadbalancer"}
    return any(n.get("type") in types for n in graph.get("nodes", []))


def is_aks_application(graph):
    types = [node.get("type") for node in graph.get("nodes", [])]
    return (
        types.count("aks") == 1
        and "k8sworkload" in types
        and "containerimage" in types
    )


def generate_aks_application_bicep(graph):
    clusters = [
        node for node in graph.get("nodes", []) if node.get("type") == "aks"
    ]
    if len(clusters) != 1:
        raise ValueError("AKS application design requires exactly one cluster")
    has_acr = any(
        node.get("type") == "acr" for node in graph.get("nodes", []))
    app = graph["id"].replace("-", "")[:16] or "app"
    lines = [
        "targetScope = 'resourceGroup'",
        "",
        "param location string = resourceGroup().location",
        "param clusterName string = 'aks-%s-${uniqueString(resourceGroup().id)}'"
        % app,
    ]
    if has_acr:
        lines.append(
            "param acrName string = 'acr%s${uniqueString(resourceGroup().id)}'"
            % app)
    lines.extend([
        "",
        "resource aks 'Microsoft.ContainerService/managedClusters@2024-02-01' = {",
        "  name: take(clusterName, 63)",
        "  location: location",
        "  identity: { type: 'SystemAssigned' }",
        "  properties: {",
        "    dnsPrefix: take('${clusterName}-dns', 54)",
        "    enableRBAC: true",
        "    oidcIssuerProfile: { enabled: true }",
        "    securityProfile: { workloadIdentity: { enabled: true } }",
        "    agentPoolProfiles: [",
        "      {",
        "        name: 'systempool'",
        "        count: 2",
        "        vmSize: 'Standard_D2ds_v6'",
        "        osType: 'Linux'",
        "        type: 'VirtualMachineScaleSets'",
        "        mode: 'System'",
        "      }",
        "    ]",
        "    networkProfile: {",
        "      networkPlugin: 'azure'",
        "      networkPluginMode: 'overlay'",
        "      loadBalancerSku: 'standard'",
        "    }",
        "  }",
        "}",
        "",
    ])
    if has_acr:
        lines.extend([
            "resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {",
            "  name: take(acrName, 50)",
            "  location: location",
            "  sku: { name: 'Standard' }",
            "  properties: { adminUserEnabled: false }",
            "}",
            "",
            "var acrPullRoleId = subscriptionResourceId(",
            "  'Microsoft.Authorization/roleDefinitions',",
            "  '7f951dda-4ed3-4680-a7ca-43fe172d538d'",
            ")",
            "",
            "resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {",
            "  name: guid(acr.id, aks.id, acrPullRoleId)",
            "  scope: acr",
            "  properties: {",
            "    principalId: aks.properties.identityProfile.kubeletidentity.objectId",
            "    principalType: 'ServicePrincipal'",
            "    roleDefinitionId: acrPullRoleId",
            "  }",
            "}",
            "",
            "output acrLoginServer string = acr.properties.loginServer",
        ])
    lines.append("output aksName string = aks.name")
    return "\n".join(lines)


def _topology_index(graph):
    nodes = graph.get("nodes", [])
    by_id = {node["id"]: node for node in nodes}
    vnets = [node for node in nodes if node["type"] == "vnet"]
    subnets = [node for node in nodes if node["type"] == "subnet"]
    if len(vnets) != 1:
        raise ValueError("network topology requires exactly one VNet")
    if not subnets:
        raise ValueError("network topology requires at least one subnet")
    if not _props(vnets[0]).get("addressPrefix"):
        raise ValueError("VNet addressPrefix is required")
    for subnet in subnets:
        props = _props(subnet)
        if props.get("parent") != vnets[0]["id"]:
            raise ValueError("each subnet must reference the VNet as parent")
        if not props.get("addressPrefix"):
            raise ValueError("each subnet requires addressPrefix")
    for node in nodes:
        if node["type"] == "nsg":
            parent = _props(node).get("parent")
            if parent not in by_id or by_id[parent]["type"] != "subnet":
                raise ValueError("%s must reference a subnet parent" % node["id"])
        if node["type"] == "loadbalancer":
            parent = _props(node).get("parent")
            if by_id.get(parent, {}).get("type") not in {"subnet", "vnet"}:
                raise ValueError(
                    "%s must reference a subnet or VNet parent" % node["id"])
        if node["type"] == "vm":
            parent = _props(node).get("parent")
            parent_type = by_id.get(parent, {}).get("type")
            if parent_type == "subnet":
                continue
            if parent_type == "vnet" and _role(node) == "jumpbox":
                continue
            raise ValueError("%s must reference a subnet parent" % node["id"])
    return by_id, vnets[0], subnets


def _management_subnet(vnet, subnets):
    network = ipaddress.ip_network(_props(vnet)["addressPrefix"], strict=True)
    prefix = max(network.prefixlen, 27)
    used = [
        ipaddress.ip_network(_props(subnet)["addressPrefix"], strict=True)
        for subnet in subnets
    ]
    block_size = 2 ** (network.max_prefixlen - prefix)
    candidate_start = int(network.broadcast_address) + 1 - block_size
    while candidate_start >= int(network.network_address):
        candidate = ipaddress.ip_network((candidate_start, prefix))
        if not any(candidate.overlaps(item) for item in used):
            return {
                "id": "management-subnet",
                "type": "subnet",
                "label": "Generated management subnet",
                "properties": {
                    "parent": vnet["id"],
                    "addressPrefix": str(candidate),
                    "role": "jumpbox",
                },
            }
        candidate_start -= block_size
    raise ValueError("VNet has no free address range for a management subnet")


def topology_warnings(graph):
    if not _network_topology_nodes(graph):
        return []
    by_id = {node["id"]: node for node in graph.get("nodes", [])}
    outside = [
        node["label"] for node in graph.get("nodes", [])
        if node["type"] == "vm"
        and by_id.get(_props(node).get("parent"), {}).get("type") == "vnet"
    ]
    warnings = []
    if outside:
        warnings.append(
            "%s %s drawn outside a subnet. A dedicated management subnet is "
            "generated because Azure VMs require subnet membership." % (
            ", ".join(outside),
            "is" if len(outside) == 1 else "are"))
    for node in graph.get("nodes", []):
        if (node["type"] == "loadbalancer"
                and by_id.get(_props(node).get("parent"), {}).get("type") == "vnet"):
            target_subnet = _load_balancer_target_subnet(node, graph, by_id)
            warnings.append(
                "%s is drawn outside a subnet; its backend tier resolves to %s."
                % (node["label"], target_subnet["label"]))
    return warnings


def _load_balancer_target_subnet(node, graph, by_id):
    parents = []
    for source, target in graph.get("edges", []):
        target_node = by_id.get(target)
        if source != node["id"] or not target_node or target_node["type"] != "vm":
            continue
        parent = by_id.get(_props(target_node).get("parent"))
        if parent and parent["type"] == "subnet":
            parents.append(parent)
    unique = {parent["id"]: parent for parent in parents}
    if len(unique) != 1:
        raise ValueError(
            "%s backend VMs must resolve to exactly one subnet" % node["id"])
    return next(iter(unique.values()))


def _load_balancer_subnet(node, graph, by_id):
    parent = by_id[_props(node)["parent"]]
    if parent["type"] == "subnet":
        return parent
    return _load_balancer_target_subnet(node, graph, by_id)


def _nsg_block(node, subnet, subnets):
    role = _role(subnet)
    sources = {
        "web": ("Internet", 80),
        "app": (next((_props(s).get("addressPrefix") for s in subnets
                      if _role(s) == "web"), "VirtualNetwork"), 8080),
        "database": (next((_props(s).get("addressPrefix") for s in subnets
                           if _role(s) == "app"), "VirtualNetwork"), 3306),
        "jumpbox": ("VirtualNetwork", 22),
    }
    source, port = sources.get(role, ("VirtualNetwork", 443))
    symbol = "nsg_%s" % _symbol(node["id"])
    return (
        "resource %s 'Microsoft.Network/networkSecurityGroups@2023-09-01' = {\n"
        "  name: 'nsg-${appName}-%s'\n"
        "  location: location\n"
        "  properties: {\n"
        "    securityRules: [\n"
        "      {\n"
        "        name: 'allow-%s'\n"
        "        properties: {\n"
        "          priority: 100\n"
        "          access: 'Allow'\n"
        "          direction: 'Inbound'\n"
        "          protocol: 'Tcp'\n"
        "          sourcePortRange: '*'\n"
        "          destinationPortRange: '%d'\n"
        "          sourceAddressPrefix: '%s'\n"
        "          destinationAddressPrefix: '*'\n"
        "        }\n"
        "      }\n"
        "    ]\n"
        "  }\n"
        "}" % (
            symbol, _bicep_string(node["id"]), role, port,
            _bicep_string(source)))


def _topology_vnet_block(vnet, subnets, nsg_by_subnet):
    entries = []
    for subnet in subnets:
        nsg = nsg_by_subnet.get(subnet["id"])
        nsg_line = ""
        if nsg:
            nsg_line = "\n        networkSecurityGroup: { id: nsg_%s.id }" % _symbol(nsg["id"])
        entries.append(
            "      {\n"
            "        name: '%s'\n"
            "        properties: {\n"
            "          addressPrefix: '%s'%s\n"
            "        }\n"
            "      }" % (
                _bicep_string(subnet["id"]),
                _bicep_string(_props(subnet)["addressPrefix"]),
                nsg_line))
    return (
        "resource vnet 'Microsoft.Network/virtualNetworks@2023-09-01' = {\n"
        "  name: 'vnet-${appName}'\n"
        "  location: location\n"
        "  properties: {\n"
        "    addressSpace: {\n"
        "      addressPrefixes: [ '%s' ]\n"
        "    }\n"
        "    subnets: [\n%s\n"
        "    ]\n"
        "  }\n"
        "}" % (
            _bicep_string(_props(vnet)["addressPrefix"]),
            "\n".join(entries)))


def _topology_subnet_ref(subnet, subnets):
    return "vnet.properties.subnets[%d].id" % subnets.index(subnet)


def _load_balancer_block(node, subnet, subnets, graph, by_id):
    symbol = "lb_%s" % _symbol(node["id"])
    access = _props(node).get("access", "internal").lower()
    targets = [
        by_id[dst] for src, dst in graph.get("edges", [])
        if src == node["id"] and dst in by_id and by_id[dst]["type"] == "vm"
    ]
    backend_role = _role(targets[0]) if targets else _role(subnet)
    default_ports = {"web": 80, "app": 8080, "database": 3306}
    port = _props(node).get("port", default_ports.get(backend_role, 80))
    if access == "public":
        frontend = (
            "    frontendIPConfigurations: [\n"
            "      { name: 'frontend', properties: { publicIPAddress: { id: pip_%s.id } } }\n"
            "    ]" % _symbol(node["id"]))
        prefix = (
            "resource pip_%s 'Microsoft.Network/publicIPAddresses@2023-09-01' = {\n"
            "  name: 'pip-${appName}-%s'\n"
            "  location: location\n"
            "  sku: { name: 'Standard' }\n"
            "  properties: { publicIPAllocationMethod: 'Static' }\n"
            "}\n\n" % (_symbol(node["id"]), _bicep_string(node["id"])))
    elif access == "internal":
        frontend = (
            "    frontendIPConfigurations: [\n"
            "      {\n"
            "        name: 'frontend'\n"
            "        properties: {\n"
            "          privateIPAllocationMethod: 'Dynamic'\n"
            "          subnet: { id: %s }\n"
            "        }\n"
            "      }\n"
            "    ]" % _topology_subnet_ref(subnet, subnets))
        prefix = ""
    else:
        raise ValueError("load balancer access must be public or internal")
    return (
        "%sresource %s 'Microsoft.Network/loadBalancers@2023-09-01' = {\n"
        "  name: 'lb-${appName}-%s'\n"
        "  location: location\n"
        "  sku: { name: 'Standard' }\n"
        "  properties: {\n"
        "%s\n"
        "    backendAddressPools: [ { name: 'backend' } ]\n"
        "    probes: [\n"
        "      { name: 'tcp-probe', properties: { protocol: 'Tcp', port: %d, intervalInSeconds: 5, numberOfProbes: 2 } }\n"
        "    ]\n"
        "    loadBalancingRules: [\n"
        "      {\n"
        "        name: 'tier-rule'\n"
        "        properties: {\n"
        "          protocol: 'Tcp'\n"
        "          frontendPort: %d\n"
        "          backendPort: %d\n"
        "          enableFloatingIP: false\n"
        "          idleTimeoutInMinutes: 4\n"
        "          loadDistribution: 'Default'\n"
        "          disableOutboundSnat: true\n"
        "          frontendIPConfiguration: { id: resourceId('Microsoft.Network/loadBalancers/frontendIPConfigurations', 'lb-${appName}-%s', 'frontend') }\n"
        "          backendAddressPool: { id: resourceId('Microsoft.Network/loadBalancers/backendAddressPools', 'lb-${appName}-%s', 'backend') }\n"
        "          probe: { id: resourceId('Microsoft.Network/loadBalancers/probes', 'lb-${appName}-%s', 'tcp-probe') }\n"
        "        }\n"
        "      }\n"
        "    ]\n"
        "  }\n"
        "}" % (
            prefix, symbol, _bicep_string(node["id"]), frontend, port, port,
            port, _bicep_string(node["id"]), _bicep_string(node["id"]),
            _bicep_string(node["id"])))


def _topology_vm_block(node, subnet, subnets, graph, by_id):
    suffix = _symbol(node["id"])
    inbound_lbs = [
        by_id[src] for src, dst in graph.get("edges", [])
        if dst == node["id"] and src in by_id and by_id[src]["type"] == "loadbalancer"
    ]
    pool_lines = ""
    if inbound_lbs:
        refs = "\n".join(
            "          { id: lb_%s.properties.backendAddressPools[0].id }"
            % _symbol(lb["id"]) for lb in inbound_lbs)
        pool_lines = "\n        loadBalancerBackendAddressPools: [\n%s\n        ]" % refs
    props = _props(node)
    tags = ["    tier: '%s'" % _bicep_string(_role(node))]
    if props.get("engine"):
        tags.append("    workload: '%s'" % _bicep_string(props["engine"]))
    return (
        "resource nic_%s 'Microsoft.Network/networkInterfaces@2023-09-01' = {\n"
        "  name: 'nic-${appName}-%s'\n"
        "  location: location\n"
        "  properties: {\n"
        "    ipConfigurations: [\n"
        "      {\n"
        "        name: 'ipconfig'\n"
        "        properties: {\n"
        "          privateIPAllocationMethod: 'Dynamic'\n"
        "          subnet: { id: %s }%s\n"
        "        }\n"
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n\n"
        "resource vm_%s 'Microsoft.Compute/virtualMachines@2023-09-01' = {\n"
        "  name: 'vm-${appName}-%s'\n"
        "  location: location\n"
        "  tags: {\n%s\n"
        "  }\n"
        "  properties: {\n"
        "    hardwareProfile: { vmSize: 'Standard_D2ds_v6' }\n"
        "    osProfile: {\n"
        "      computerName: '%s'\n"
        "      adminUsername: adminUsername\n"
        "      adminPassword: adminPassword\n"
        "    }\n"
        "    storageProfile: {\n"
        "      imageReference: { publisher: 'Canonical', offer: '0001-com-ubuntu-server-jammy', sku: '22_04-lts-gen2', version: 'latest' }\n"
        "      osDisk: { createOption: 'FromImage', managedDisk: { storageAccountType: 'Premium_LRS' } }\n"
        "    }\n"
        "    networkProfile: { networkInterfaces: [ { id: nic_%s.id } ] }\n"
        "  }\n"
        "}" % (
            suffix, _bicep_string(node["id"]),
            _topology_subnet_ref(subnet, subnets), pool_lines,
            suffix, _bicep_string(node["id"]), "\n".join(tags),
            _bicep_string(node["id"][:63]), suffix))


def _generate_network_topology_bicep(graph):
    by_id, vnet, subnets = _topology_index(graph)
    nodes = graph.get("nodes", [])
    nsgs = [node for node in nodes if node["type"] == "nsg"]
    lbs = [node for node in nodes if node["type"] == "loadbalancer"]
    vms = [node for node in nodes if node["type"] == "vm"]
    outside_vms = [
        node for node in vms
        if by_id[_props(node)["parent"]]["type"] == "vnet"
    ]
    if outside_vms:
        management = _management_subnet(vnet, subnets)
        subnets = subnets + [management]
        by_id[management["id"]] = management
        management_nsg = {
            "id": "management-nsg",
            "type": "nsg",
            "label": "Generated management NSG",
            "properties": {"parent": management["id"]},
        }
        nsgs = nsgs + [management_nsg]
        vms = [
            dict(node, properties=dict(
                _props(node), parent=management["id"]))
            if node in outside_vms else node
            for node in vms
        ]
    nsg_by_subnet = {_props(node)["parent"]: node for node in nsgs}
    app = graph["id"].replace("-", "")[:16] or "app"
    lines = [
        "param appName string = '%s'" % app,
        "param location string = resourceGroup().location",
        "param adminUsername string = 'azureuser'",
        "@secure()",
        "param adminPassword string = newGuid()",
        "",
    ]

    def add(title, block):
        lines.extend(["// %s" % title, block, ""])

    for nsg in nsgs:
        subnet = by_id[_props(nsg)["parent"]]
        add("Network security group: %s" % nsg["label"],
            _nsg_block(nsg, subnet, subnets))
    add("Virtual network and tier subnets",
        _topology_vnet_block(vnet, subnets, nsg_by_subnet))
    for lb in lbs:
        subnet = _load_balancer_subnet(lb, graph, by_id)
        add("%s load balancer: %s" % (
            _props(lb).get("access", "internal").title(), lb["label"]),
            _load_balancer_block(lb, subnet, subnets, graph, by_id))
    for vm in vms:
        subnet = by_id[_props(vm)["parent"]]
        add("Virtual machine: %s" % vm["label"],
            _topology_vm_block(vm, subnet, subnets, graph, by_id))
    return "\n".join(lines).strip()


def _subnet_ref(name):
    idx = _SUBNETS.index(name)
    return "vnet.properties.subnets[%d].id" % idx


def _vnet_block():
    subnet_prefixes = {"appgw": "10.0.1.0/24", "pe": "10.0.2.0/24", "vm": "10.0.3.0/24"}
    subnets = "\n".join(
        "      { name: '%s', properties: { addressPrefix: '%s' } }" % (s, subnet_prefixes[s])
        for s in _SUBNETS)
    return ("resource vnet 'Microsoft.Network/virtualNetworks@2023-09-01' = {\n"
            "  name: 'vnet-${appName}'\n  location: location\n  properties: {\n"
            "    addressSpace: { addressPrefixes: [ '10.0.0.0/16' ] }\n"
            "    subnets: [\n%s\n    ]\n  }\n}" % subnets)


def _waf_block():
    return ("resource waf 'Microsoft.Network/ApplicationGatewayWebApplicationFirewallPolicies@2023-09-01' = {\n"
            "  name: 'waf-${appName}'\n  location: location\n  properties: {\n"
            "    policySettings: { state: 'Enabled', mode: 'Prevention' }\n"
            "    managedRules: { managedRuleSets: [ { ruleSetType: 'OWASP', ruleSetVersion: '3.2' } ] }\n"
            "  }\n}")


def _appgateway_block(has_waf):
    fw = "\n    firewallPolicy: { id: waf.id }" if has_waf else ""
    return ("resource pip 'Microsoft.Network/publicIPAddresses@2023-09-01' = {\n"
            "  name: 'pip-${appName}'\n  location: location\n  sku: { name: 'Standard' }\n"
            "  properties: { publicIPAllocationMethod: 'Static' }\n}\n\n"
            "resource agw 'Microsoft.Network/applicationGateways@2023-09-01' = {\n"
            "  name: 'agw-${appName}'\n  location: location\n  properties: {\n"
            "    sku: { name: 'WAF_v2', tier: 'WAF_v2', capacity: 2 }%s\n"
            "    gatewayIPConfigurations: [ { name: 'gwip', properties: { subnet: { id: %s } } } ]\n"
            "    frontendIPConfigurations: [ { name: 'feip', properties: { publicIPAddress: { id: pip.id } } } ]\n"
            "    frontendPorts: [ { name: 'port443', properties: { port: 443 } } ]\n"
            "    backendAddressPools: [ { name: 'apimpool' } ]\n"
            "    backendHttpSettingsCollection: [ { name: 'https', properties: { port: 443, protocol: 'Https' } } ]\n"
            "    httpListeners: [ { name: 'l1', properties: { frontendIPConfiguration: { id: resourceId('Microsoft.Network/applicationGateways/frontendIPConfigurations', 'agw-${appName}', 'feip') }, frontendPort: { id: resourceId('Microsoft.Network/applicationGateways/frontendPorts', 'agw-${appName}', 'port443') }, protocol: 'Https' } } ]\n"
            "    requestRoutingRules: [ { name: 'r1', properties: { ruleType: 'Basic', priority: 100, httpListener: { id: resourceId('Microsoft.Network/applicationGateways/httpListeners', 'agw-${appName}', 'l1') }, backendAddressPool: { id: resourceId('Microsoft.Network/applicationGateways/backendAddressPools', 'agw-${appName}', 'apimpool') }, backendHttpSettings: { id: resourceId('Microsoft.Network/applicationGateways/backendHttpSettingsCollection', 'agw-${appName}', 'https') } } } ]\n"
            "  }\n}" % (fw, _subnet_ref("appgw")))


def _apim_block():
    return ("resource apim 'Microsoft.ApiManagement/service@2023-05-01-preview' = {\n"
            "  name: 'apim-${appName}'\n  location: location\n"
            "  sku: { name: 'Developer', capacity: 1 }\n"
            "  properties: { publisherEmail: 'admin@example.com', publisherName: 'MeshOps' }\n}")


def _aks_block():
    return ("resource aks 'Microsoft.ContainerService/managedClusters@2024-02-01' = {\n"
            "  name: 'aks-${appName}'\n  location: location\n"
            "  identity: { type: 'SystemAssigned' }\n  properties: {\n"
            "    dnsPrefix: '${appName}-dns'\n    enableRBAC: true\n"
            "    agentPoolProfiles: [ { name: 'systempool', count: 2, vmSize: 'Standard_D2ds_v6', mode: 'System' } ]\n"
            "  }\n}")


def _keyvault_block():
    return ("resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {\n"
            "  name: 'kv-${appName}'\n  location: location\n  properties: {\n"
            "    sku: { family: 'A', name: 'standard' }\n    tenantId: subscription().tenantId\n"
            "    enableRbacAuthorization: true\n    accessPolicies: []\n  }\n}")


def _acr_block():
    return ("resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {\n"
            "  name: 'acr${appName}'\n  location: location\n  sku: { name: 'Premium' }\n}")


def _appconfig_block():
    return ("resource appcfg 'Microsoft.AppConfiguration/configurationStores@2023-03-01' = {\n"
            "  name: 'appcs-${appName}'\n  location: location\n  sku: { name: 'standard' }\n}")


def _identity_block():
    return ("resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {\n"
            "  name: 'id-${appName}'\n  location: location\n}")


def _privatedns_block():
    return ("resource pdns 'Microsoft.Network/privateDnsZones@2020-06-01' = {\n"
            "  name: 'privatelink.azurecr.io'\n  location: 'global'\n}")


def _vm_block():
    return ("resource nic 'Microsoft.Network/networkInterfaces@2023-09-01' = {\n"
            "  name: 'nic-${appName}'\n  location: location\n  properties: {\n"
            "    ipConfigurations: [ { name: 'ipcfg', properties: { subnet: { id: %s }, privateIPAllocationMethod: 'Dynamic' } } ]\n"
            "  }\n}\n\n"
            "resource jumpbox 'Microsoft.Compute/virtualMachines@2023-09-01' = {\n"
            "  name: 'vm-${appName}'\n  location: location\n  properties: {\n"
            "    hardwareProfile: { vmSize: 'Standard_D2ds_v6' }\n"
            "    osProfile: { computerName: 'jumpbox', adminUsername: 'azureuser', adminPassword: adminPassword }\n"
            "    storageProfile: {\n"
            "      imageReference: { publisher: 'Canonical', offer: '0001-com-ubuntu-server-jammy', sku: '22_04-lts-gen2', version: 'latest' }\n"
            "      osDisk: { createOption: 'FromImage', managedDisk: { storageAccountType: 'Premium_LRS' } }\n"
            "    }\n    networkProfile: { networkInterfaces: [ { id: nic.id } ] }\n  }\n}" % _subnet_ref("vm"))


def _private_endpoint_block(present):
    # Point the PE at a real resource we're also creating, when possible.
    if "keyvault" in present:
        target, group = "kv.id", "vault"
    elif "acr" in present:
        target, group = "acr.id", "registry"
    elif "appconfig" in present:
        target, group = "appcfg.id", "configurationStores"
    else:
        target, group = "vnet.id", "vault"
    return ("resource pe 'Microsoft.Network/privateEndpoints@2023-09-01' = {\n"
            "  name: 'pe-${appName}'\n  location: location\n  properties: {\n"
            "    subnet: { id: %s }\n"
            "    privateLinkServiceConnections: [ { name: 'plsc', properties: { privateLinkServiceId: %s, groupIds: [ '%s' ] } } ]\n"
            "  }\n}" % (_subnet_ref("pe"), target, group))


def generate_azure_bicep(graph):
    if _network_topology_nodes(graph):
        return _generate_network_topology_bicep(graph)

    present = _present(graph)
    app = graph["id"].replace("-", "")[:16] or "app"

    head = ["param appName string = '%s'" % app,
            "param location string = resourceGroup().location"]
    if "vm" in present:
        head.append("@secure()\nparam adminPassword string = newGuid()")
    head.append("")

    blocks = []

    def add(title, block):
        blocks.append("// %s" % title)
        blocks.append(block)
        blocks.append("")

    if present & _NEEDS_VNET:
        add("Virtual network + subnets", _vnet_block())
    if "managedidentity" in present:
        add("User-assigned managed identity", _identity_block())
    if "keyvault" in present:
        add("Key Vault", _keyvault_block())
    if "acr" in present:
        add("Container Registry", _acr_block())
    if "appconfig" in present:
        add("App Configuration", _appconfig_block())
    if "privatedns" in present:
        add("Private DNS zone", _privatedns_block())
    if "waf" in present:
        add("WAF policy", _waf_block())
    if "appgateway" in present:
        add("Application Gateway (WAF_v2) + public IP", _appgateway_block("waf" in present))
    if "apim" in present:
        add("API Management", _apim_block())
    if "aks" in present:
        add("AKS managed cluster", _aks_block())
    if "vm" in present:
        add("Jumpbox VM + NIC", _vm_block())
    if "privateendpoint" in present:
        add("Private Endpoint", _private_endpoint_block(present))

    return "\n".join(head + blocks).strip()


# ---------------------------------------------------------------------------
# Safe-subset template: only the cheap, fast, demo-safe resources from the
# diagram (Managed Identity, Key Vault, ACR Basic). This is what actually gets
# provisioned for real on stage -- everything else (App Gateway, APIM, AKS)
# is validated-only because it is slow and costly to create.
# ---------------------------------------------------------------------------
SAFE_TYPES = ["managedidentity", "keyvault", "acr"]


def generate_safe_subset_bicep(graph, suffix):
    """Return Bicep for only the demo-safe resource types present in `graph`.
    `suffix` keeps globally-unique names (KV/ACR) collision-free per deploy."""
    present = _present(graph)
    lines = ["param location string = resourceGroup().location",
             "param suffix string = '%s'" % suffix, ""]
    outputs = []

    if "managedidentity" in present:
        lines += ["// User-assigned managed identity",
                  "resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {",
                  "  name: 'id-wb-${suffix}'",
                  "  location: location",
                  "}", ""]
        outputs.append("output identityId string = uami.id")
    if "keyvault" in present:
        lines += ["// Key Vault",
                  "resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {",
                  "  name: 'kv-wb-${suffix}'",
                  "  location: location",
                  "  properties: {",
                  "    sku: { family: 'A', name: 'standard' }",
                  "    tenantId: subscription().tenantId",
                  "    enableRbacAuthorization: true",
                  "    accessPolicies: []",
                  "  }",
                  "}", ""]
        outputs.append("output keyVaultUri string = kv.properties.vaultUri")
    if "acr" in present:
        lines += ["// Container Registry (Basic)",
                  "resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {",
                  "  name: 'acrwb${suffix}'",
                  "  location: location",
                  "  sku: { name: 'Basic' }",
                  "}", ""]
        outputs.append("output acrLoginServer string = acr.properties.loginServer")

    lines += outputs
    return "\n".join(lines).strip()


def has_safe_subset(graph):
    return bool(_present(graph) & set(SAFE_TYPES))

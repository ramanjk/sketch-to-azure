"""Azure-infra Bicep generation for the Whiteboard -> App hack.

Given a parsed graph whose nodes use Azure service types (as returned by the
GPT-4o vision parser on a real Azure architecture diagram), emit a single,
**compile-valid** Bicep template. "Compile-valid" means `bicep build` succeeds
-- every block below was verified against Bicep CLI 0.45.

The app-centric generator in server.py handles the simpler web-app patterns;
this module kicks in when the diagram is an Azure infrastructure diagram.
"""

# Azure service node types this generator understands.
AZURE_TYPES = {
    "appgateway", "waf", "apim", "aks", "keyvault", "acr", "appconfig",
    "managedidentity", "vm", "privatedns", "privateendpoint",
}
# Types that require a VNet + subnets to be emitted.
_NEEDS_VNET = {"appgateway", "vm", "privateendpoint"}
# Fixed subnet order so index references stay stable.
_SUBNETS = ["appgw", "pe", "vm"]


def is_azure_infra(graph):
    return any(n.get("type") in AZURE_TYPES for n in graph.get("nodes", []))


def _present(graph):
    return {n["type"] for n in graph.get("nodes", [])}


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
            "    agentPoolProfiles: [ { name: 'systempool', count: 2, vmSize: 'Standard_D2s_v5', mode: 'System' } ]\n"
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
            "    hardwareProfile: { vmSize: 'Standard_D2s_v5' }\n"
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

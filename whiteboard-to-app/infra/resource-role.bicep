targetScope = 'resourceGroup'

param principalId string
param resourceName string
param roleDefinitionId string

var roleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  roleDefinitionId
)

resource target 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: resourceName
}

resource assignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(target.id, principalId, roleId)
  scope: target
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: roleId
  }
}

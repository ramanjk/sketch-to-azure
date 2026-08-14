targetScope = 'resourceGroup'

param principalId string
param roleDefinitionId string

var roleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  roleDefinitionId
)

resource assignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, principalId, roleId)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: roleId
  }
}

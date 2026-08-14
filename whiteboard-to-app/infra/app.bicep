targetScope = 'resourceGroup'

@description('Container App name.')
param appName string = 'whiteboard-agent'

param location string = resourceGroup().location
param registryName string
param environmentName string
param identityName string
param imageTag string = 'latest'

param azureOpenAIEndpoint string
param azureOpenAIDeployment string
param azureOpenAIApiVersion string
param azureOpenAIResourceGroup string
param azureOpenAIResourceName string
param deploymentResourceGroup string

@secure()
param agentApiKey string

@secure()
param agentPlanSigningKey string

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: environmentName
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: identityName
}

module deploymentContributor 'resource-group-role.bicep' = {
  name: 'deployment-contributor'
  scope: resourceGroup(deploymentResourceGroup)
  params: {
    principalId: identity.properties.principalId
    roleDefinitionId: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
  }
}

module deploymentRbacAdmin 'resource-group-role.bicep' = {
  name: 'deployment-rbac-administrator'
  scope: resourceGroup(deploymentResourceGroup)
  params: {
    principalId: identity.properties.principalId
    roleDefinitionId: 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
  }
}

module modelUser 'resource-role.bicep' = {
  name: 'azure-openai-user'
  scope: resourceGroup(azureOpenAIResourceGroup)
  params: {
    principalId: identity.properties.principalId
    resourceName: azureOpenAIResourceName
    roleDefinitionId: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8012
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: identity.id
        }
      ]
      secrets: [
        {
          name: 'agent-api-key'
          value: agentApiKey
        }
        {
          name: 'agent-plan-signing-key'
          value: agentPlanSigningKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'agent-api'
          image: '${registry.properties.loginServer}/whiteboard-to-azure:${imageTag}'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: identity.properties.clientId
            }
            {
              name: 'AZURE_SUBSCRIPTION_ID'
              value: subscription().subscriptionId
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: azureOpenAIEndpoint
            }
            {
              name: 'AZURE_OPENAI_DEPLOYMENT'
              value: azureOpenAIDeployment
            }
            {
              name: 'AZURE_OPENAI_API_VERSION'
              value: azureOpenAIApiVersion
            }
            {
              name: 'DEPLOY_RG'
              value: deploymentResourceGroup
            }
            {
              name: 'DEPLOY_MODE'
              value: 'real'
            }
            {
              name: 'AGENT_API_KEY'
              secretRef: 'agent-api-key'
            }
            {
              name: 'AGENT_PLAN_SIGNING_KEY'
              secretRef: 'agent-plan-signing-key'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

output fqdn string = app.properties.configuration.ingress.fqdn
output url string = 'https://${app.properties.configuration.ingress.fqdn}'

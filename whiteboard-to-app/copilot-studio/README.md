# Microsoft 365 Copilot agent setup

This folder contains the custom connector contract and agent instructions for
the Whiteboard to Azure Copilot Studio agent.

## 1. Host and secure the API

The repository includes a pinned container image and Azure Container Apps
Bicep deployment. Export:

```text
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=<vision-capable-deployment>
AZURE_OPENAI_API_VERSION=<supported-version>
AGENT_API_KEY=<random-32-byte-or-longer-secret>
AGENT_PLAN_SIGNING_KEY=<different-random-secret>
AZURE_OPENAI_RESOURCE_GROUP=<resource-group-containing-the-model>
AZURE_OPENAI_RESOURCE_NAME=<Azure-OpenAI-resource-name>
DEPLOY_RG=rg-whiteboard-demo
```

Then run `./deploy-container-app.sh`. It creates a dedicated resource group,
Azure Container Registry, Container Apps environment, user-assigned managed
identity, and HTTPS Container App; builds the image remotely; grants model-user
access to Azure OpenAI plus Contributor and Role Based Access Control
Administrator only on `DEPLOY_RG`; and verifies the HTTPS endpoint. The latter
is required for generated AKS-to-ACR `AcrPull` assignments. The script prints
the connector hostname.

The deployer must be able to create resource groups, role assignments, ACR,
Container Apps, Log Analytics, and deployments. Runtime secrets are stored as
Container App secrets and the workload uses managed identity for Azure access.
For production, put API Management in front of the app and replace connector
API-key authentication with Microsoft Entra ID.

Replace `REPLACE_WITH_YOUR_API_HOST` in `openapi.json` with the HTTPS hostname.
Do not include `https://` or a path.

## 2. Create the custom connector

1. In Power Apps or Power Automate, open **Custom connectors** and select
   **New custom connector > Import an OpenAPI file**.
2. Import `openapi.json`.
3. Confirm the authentication type is **API key**, parameter label is
   `x-api-key`, parameter name is `x-api-key`, and location is **Header**.
4. Create the connector, create a connection using `AGENT_API_KEY`, and test
   `AnalyzeArchitectureDiagram` with a small PNG or JPEG encoded as base64.
5. Confirm the result includes `validation.validated`, `deploymentEligible`,
   and `planToken`.

## 3. Create the analysis flow

Create a solution-aware cloud flow named **Analyze Architecture Diagram**:

1. Use **When an agent calls the flow** as the trigger.
2. Add a file input named `ArchitectureDiagram`.
3. Call **Analyze architecture diagram** from the custom connector. Map the
   trigger file content to `imageBase64` and its media type to `contentType`.
   If the trigger exposes binary content, use the Power Automate `base64()`
   expression.
4. Call **Preview infrastructure plan** with the returned `planToken`.
5. Return the graph, Bicep, Kubernetes `k8s` manifest bundle, warnings,
   unsupported resources, validation, deployment eligibility, plan token, and
   what-if output to the agent. Do not condition the `k8s` output on the
   response kind; AKS plans return both Bicep and Kubernetes manifests.

The exact file-content property name varies by the trigger designer version.
Use the file's content bytes, not a public sharing URL.

## 4. Create the approval/deployment flow

Create a second solution-aware cloud flow named
**Deploy Approved Architecture Plan**:

1. Use **When an agent calls the flow** with `PlanToken`, `PlanSummary`, and
   `Approver` text inputs.
2. Call **Preview infrastructure plan** again. Stop if Bicep validation or
   Azure what-if fails.
3. Add **Start and wait for an approval**. Include `PlanSummary` and the what-if
   output in the approval details.
4. Add a condition that the approval outcome equals `Approve`.
5. Only in the approved branch, call **Deploy approved plan** with:
   `planToken = PlanToken`, `approved = true`, and
   `approvalId =` the approval action identifier.
6. Return deployment status, resource group, deployment name, and errors to the
   agent. In the rejected branch, return `Deployment rejected`; do not call the
   deployment action.

Restrict flow ownership and run-only permissions. Use an approver group rather
than allowing arbitrary approver addresses in production.

## 5. Create and publish the Copilot Studio agent

1. Create an agent named **Whiteboard to Azure**.
2. Paste `agent-instructions.txt` into the agent instructions.
3. Add both flows as agent actions.
4. Enable file uploads for the conversation and map the uploaded file to the
   analysis flow input.
5. Add suggested prompts such as:
   - `Analyze this Azure architecture diagram`
   - `Generate and validate Bicep from this diagram`
   - `Preview the approved infrastructure plan`
6. Test analysis, invalid images, failed validation, rejection, expired tokens,
   warnings, repeated resource instances, one-cluster/multiple-workload AKS
   diagrams, failed Azure what-if, and successful safe-subset deployment.
7. Publish the agent to Microsoft 365 Copilot and share it only with the pilot
   security group before organization-wide release.

The signed plan token prevents a graph from being changed between analysis and
deployment, includes the exact generated Bicep used by preview, and expires
after `AGENT_PLAN_TTL_SECONDS` (24 hours by default).
For long-running production approvals, persist immutable plans and approval
records in a database instead of increasing the token lifetime.

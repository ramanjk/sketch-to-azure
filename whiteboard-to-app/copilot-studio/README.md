# Microsoft 365 Copilot agent setup

This folder contains the copy/paste configuration and custom connector contract
for the Whiteboard to Azure agent.

## Included files

| File | Used for |
|---|---|
| `agent-builder-prompt.txt` | Optional prompt for the **Describe** tab in Microsoft 365 Agent Builder |
| `agent-description.txt` | **Description** field on the **Configure** tab |
| `agent-instructions.txt` | **Instructions** field on the **Configure** tab |
| `starter-prompts.md` | Names and prompts for **Starter prompts** |
| `openapi.json` | Custom connector import in Power Apps or Power Automate |

An icon is optional. If you upload one, Microsoft currently requires a PNG no
larger than 192x192 pixels and 1 MB; a transparent background works best.

> **Important:** Microsoft 365 Copilot **Agents > New agent** creates the
> initial declarative agent, but Agent Builder does not support the external
> actions required by this project. Create the shell there, then use **Copy to
> Copilot Studio** to add the connector-backed flows and publish the functional
> agent.

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

Set the `host` property in `openapi.json` to the HTTPS hostname printed by the
deployment script. Do not include `https://` or a path. The checked-in contract
currently contains the demo deployment hostname; replace it when deploying
your own instance.

## 2. Create the custom connector

1. In Power Apps or Power Automate, open **Custom connectors** and select
   **New custom connector > Import an OpenAPI file**.
2. Import `openapi.json`.
3. Confirm the authentication type is **API key**, parameter label is
   `x-api-key`, parameter name is `x-api-key`, and location is **Header**.
4. Create the connector, create a connection using `AGENT_API_KEY`, and test
   `AnalyzeArchitectureDiagram` with a PNG, JPEG, or VSDX encoded as base64.
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
   The response also includes `references`, the source-attributed architecture
   patterns selected from services detected in the diagram.
   Present `manualActions` and `validation.required_parameters` to the user
   before requesting approval. Do not call Preview or Deploy until required
   inputs and prerequisite checks are complete.
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

## 5. Create the agent in Microsoft 365 Copilot

1. In Microsoft 365 Copilot, select **Agents > New agent**.
2. Either paste `agent-builder-prompt.txt` into **Describe**, or select
   **Skip to configure** for deterministic setup.
3. On **Configure**, enter:
   - **Name:** `Whiteboard to Azure`
   - **Description:** paste `agent-description.txt`
   - **Instructions:** paste `agent-instructions.txt`
4. Do not add a knowledge source unless you have approved architecture
   standards in SharePoint or OneDrive. The uploaded diagram is action input,
   not an Agent Builder knowledge source.
5. Leave **Create images** off. **Create documents, charts, and code** is
   optional and is not required for Bicep generation because the backend
   generates and validates the template.
6. Add the four entries from `starter-prompts.md`.
7. Select **Create**, test the basic agent, and then select **Copy to Copilot
   Studio**. Choose the Power Platform environment that contains the custom
   connector and flows.

## 6. Complete and publish the agent in Copilot Studio

1. Open the copied agent and add the **Analyze Architecture Diagram** and
   **Deploy Approved Architecture Plan** flows as tools.
2. Enable file uploads and map the uploaded file to the analysis flow's
   `ArchitectureDiagram` input.
3. Confirm the analysis tool description tells the orchestrator to call it when
   the user uploads a PNG, JPEG, WebP, SVG, or VSDX architecture diagram.
4. Confirm the deployment tool requires explicit user intent and executes the
   approval flow rather than calling the deployment connector action directly.
5. Test analysis, invalid images, failed validation, rejection, expired tokens,
   warnings, repeated resource instances, one-cluster/multiple-workload AKS
   diagrams, failed Azure what-if, and successful safe-subset deployment.
6. Publish the agent to Microsoft 365 Copilot and share it only with the pilot
   security group before organization-wide release.

The signed plan token prevents a graph from being changed between analysis and
deployment, includes the exact generated Bicep used by preview, and expires
after `AGENT_PLAN_TTL_SECONDS` (24 hours by default).
For long-running production approvals, persist immutable plans and approval
records in a database instead of increasing the token lifetime.

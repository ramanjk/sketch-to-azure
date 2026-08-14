#!/usr/bin/env bash
set -euo pipefail

required=(
  AZURE_OPENAI_ENDPOINT
  AZURE_OPENAI_DEPLOYMENT
  AZURE_OPENAI_API_VERSION
  AZURE_OPENAI_RESOURCE_GROUP
  AZURE_OPENAI_RESOURCE_NAME
  AGENT_API_KEY
  AGENT_PLAN_SIGNING_KEY
)
for name in "${required[@]}"; do
  value="$(printenv "$name" 2>/dev/null || true)"
  if [ -z "$value" ]; then
    echo "$name is required" >&2
    exit 1
  fi
done

APP_RESOURCE_GROUP="${APP_RESOURCE_GROUP:-rg-whiteboard-agent}"
DEPLOY_RG="${DEPLOY_RG:-rg-whiteboard-demo}"
LOCATION="${LOCATION:-eastus}"
NAME_PREFIX="${NAME_PREFIX:-whiteboard}"
APP_NAME="${APP_NAME:-whiteboard-agent}"
IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)}"

az account show --output none
az group create --name "$APP_RESOURCE_GROUP" --location "$LOCATION" --output none
az group create --name "$DEPLOY_RG" --location "$LOCATION" --output none

foundation_outputs="$(
  az deployment group create \
    --resource-group "$APP_RESOURCE_GROUP" \
    --name "whiteboard-foundation" \
    --template-file infra/foundation.bicep \
    --parameters namePrefix="$NAME_PREFIX" location="$LOCATION" \
    --query properties.outputs \
    --output json
)"

read -r registry_name environment_name identity_name <<EOF
$(printf '%s' "$foundation_outputs" | python3 -c '
import json, sys
outputs = json.load(sys.stdin)
print(outputs["registryName"]["value"], outputs["environmentName"]["value"],
      outputs["identityName"]["value"])
')
EOF

az acr build \
  --registry "$registry_name" \
  --image "whiteboard-to-azure:$IMAGE_TAG" \
  --file Dockerfile \
  .

parameters_file="$(mktemp)"
trap 'rm -f "$parameters_file"' EXIT
chmod 600 "$parameters_file"

export APP_NAME LOCATION REGISTRY_NAME="$registry_name"
export ENVIRONMENT_NAME="$environment_name" IDENTITY_NAME="$identity_name"
export IMAGE_TAG DEPLOY_RG

python3 - "$parameters_file" <<'PY'
import json
import os
import sys

values = {
    "appName": os.environ.get("APP_NAME", "whiteboard-agent"),
    "location": os.environ.get("LOCATION", "eastus"),
    "registryName": os.environ["REGISTRY_NAME"],
    "environmentName": os.environ["ENVIRONMENT_NAME"],
    "identityName": os.environ["IDENTITY_NAME"],
    "imageTag": os.environ["IMAGE_TAG"],
    "azureOpenAIEndpoint": os.environ["AZURE_OPENAI_ENDPOINT"],
    "azureOpenAIDeployment": os.environ["AZURE_OPENAI_DEPLOYMENT"],
    "azureOpenAIApiVersion": os.environ["AZURE_OPENAI_API_VERSION"],
    "azureOpenAIResourceGroup": os.environ["AZURE_OPENAI_RESOURCE_GROUP"],
    "azureOpenAIResourceName": os.environ["AZURE_OPENAI_RESOURCE_NAME"],
    "deploymentResourceGroup": os.environ["DEPLOY_RG"],
    "agentApiKey": os.environ["AGENT_API_KEY"],
    "agentPlanSigningKey": os.environ["AGENT_PLAN_SIGNING_KEY"],
}
payload = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {key: {"value": value} for key, value in values.items()},
}
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump(payload, stream)
PY

fqdn="$(
  az deployment group create \
    --resource-group "$APP_RESOURCE_GROUP" \
    --name "whiteboard-app-$IMAGE_TAG" \
    --template-file infra/app.bicep \
    --parameters "@$parameters_file" \
    --query properties.outputs.fqdn.value \
    --output tsv
)"

health_code="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    "https://$fqdn/api/config"
)"
if [ "$health_code" != "200" ]; then
  echo "Container App health check failed with HTTP $health_code" >&2
  exit 1
fi

cat <<EOF
Container App: https://$fqdn
Connector host: $fqdn

Replace REPLACE_WITH_YOUR_API_HOST in copilot-studio/openapi.json with:
$fqdn
EOF

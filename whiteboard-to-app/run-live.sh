#!/usr/bin/env bash
# Launch the Whiteboard -> App server with LIVE GPT-4o vision + real Azure deploy.
#
# Auth is via your logged-in Azure CLI (`az login`). If your Azure OpenAI
# resource has key auth enabled you can instead export AZURE_OPENAI_API_KEY.
# No secrets are stored in this file. Copy .env.example to .env and edit, or
# just export the variables below before running.
set -euo pipefail

# --- Azure OpenAI (vision) --- REQUIRED: set to your own resource ------------
export AZURE_OPENAI_ENDPOINT="${AZURE_OPENAI_ENDPOINT:-https://<your-aoai>.openai.azure.com}"
export AZURE_OPENAI_DEPLOYMENT="${AZURE_OPENAI_DEPLOYMENT:-gpt-4o}"   # vision-capable
export AZURE_OPENAI_API_VERSION="${AZURE_OPENAI_API_VERSION:-2024-08-01-preview}"
# export AZURE_OPENAI_API_KEY="..."   # optional; omit to use your `az login` token

# --- Optional real deploy of the demo-safe subset (Identity + Key Vault + ACR)
# into a DEDICATED resource group. Heavy resources stay validate-only.
# export DEPLOY_RG="rg-whiteboard-demo"
# export DEPLOY_MODE="real"    # 'real' provisions safe subset; 'whatif' previews full template

# Load a local .env if present (gitignored).
if [ -f "$(dirname "$0")/.env" ]; then
  set -a; . "$(dirname "$0")/.env"; set +a
fi

cd "$(dirname "$0")"
echo "Starting Whiteboard -> App (LIVE vision) on http://localhost:${PORT:-8012}"
exec python3 server.py

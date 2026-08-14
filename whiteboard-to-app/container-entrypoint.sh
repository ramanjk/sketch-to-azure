#!/usr/bin/env sh
set -eu

if [ -z "${AZURE_CLIENT_ID:-}" ]; then
  echo "AZURE_CLIENT_ID is required for managed identity authentication" >&2
  exit 1
fi

attempt=1
until az login --identity --client-id "$AZURE_CLIENT_ID" \
  --allow-no-subscriptions --output none 2>/dev/null; do
  if [ "$attempt" -ge 6 ]; then
    echo "Managed identity login failed after $attempt attempts" >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 5
done

if [ -n "${AZURE_SUBSCRIPTION_ID:-}" ]; then
  az account set --subscription "$AZURE_SUBSCRIPTION_ID"
fi

exec python3 /app/server.py

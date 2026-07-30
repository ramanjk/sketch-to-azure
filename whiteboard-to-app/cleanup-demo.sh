#!/usr/bin/env bash
# Clean up resources provisioned by the Whiteboard -> App demo.
#
# Each real deploy creates uniquely-suffixed resources (id-wb-*, kv-wb-*,
# acrwb*) in the dedicated RG. This removes them so repeated demos stay tidy
# and cost nothing between runs.
set -uo pipefail

RG="${DEPLOY_RG:-rg-whiteboard-demo}"

echo "Cleaning demo resources in $RG ..."

# ACR + Managed Identity delete cleanly.
for acr in $(az acr list -g "$RG" --query "[?starts_with(name,'acrwb')].name" -o tsv); do
  echo "  deleting ACR $acr"; az acr delete -n "$acr" -g "$RG" -y >/dev/null 2>&1
done
for id in $(az identity list -g "$RG" --query "[?starts_with(name,'id-wb-')].name" -o tsv); do
  echo "  deleting identity $id"; az identity delete -n "$id" -g "$RG" >/dev/null 2>&1
done
# Key Vault: delete then purge (soft-delete) so names can be reused.
for kv in $(az keyvault list -g "$RG" --query "[?starts_with(name,'kv-wb-')].name" -o tsv); do
  echo "  deleting Key Vault $kv"; az keyvault delete -n "$kv" -g "$RG" >/dev/null 2>&1
  echo "  purging Key Vault $kv";  az keyvault purge  -n "$kv" >/dev/null 2>&1
done

echo "Remaining in $RG:"
az resource list -g "$RG" --query "[].name" -o tsv 2>/dev/null || true
echo "Done. (To delete the RG entirely: az group delete -n $RG --yes)"

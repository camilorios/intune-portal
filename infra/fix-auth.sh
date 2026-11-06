#!/usr/bin/env bash
# Fuerza la configuración de App Service Authentication v2 vía ARM (sin depender de la extensión authV2).
set -euo pipefail
SUB="${SUB:?}"; RG="${RG:?}"; APP="${APP:?}"
U="https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Web/sites/$APP/config/authsettingsV2?api-version=2022-03-01"
az rest --method get --url "$U" > auth.json
jq '.properties.platform.enabled=true
  | .properties.globalValidation.requireAuthentication=true
  | .properties.globalValidation.unauthenticatedClientAction="RedirectToLoginPage"
  | .properties.globalValidation.redirectToProvider="azureactivedirectory"
  | .properties.globalValidation.excludedPaths=["/onboarding/callback"]' auth.json > auth2.json
az rest --method put --url "$U" --body @auth2.json \
  --query "{enabled:properties.platform.enabled,global:properties.globalValidation,aadClient:properties.identityProviders.azureActiveDirectory.registration.clientId,aadEnabled:properties.identityProviders.azureActiveDirectory.enabled}" -o json

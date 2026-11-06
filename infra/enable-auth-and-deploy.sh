#!/usr/bin/env bash
# Activa el login de técnicos (App Service Authentication con Entra ID, solo tu tenant)
# y redespliega el código. Uso en Cloud Shell:
#   SUB=... RG=rg-intune-portal-westus3 APP=intune-portal-camilo bash enable-auth-and-deploy.sh
set -euo pipefail
SUB="${SUB:?}"; RG="${RG:?}"; APP="${APP:?}"; REPO="camilorios/intune-portal"
az account set --subscription "$SUB"
TENANT_ID=$(az account show --query tenantId -o tsv)
URL="https://$APP.azurewebsites.net"

ADMIN_APP_ID=$(az ad app list --display-name "Intune Portal Admin" --query "[0].appId" -o tsv)
if [ -z "$ADMIN_APP_ID" ]; then
  ADMIN_APP_ID=$(az ad app create --display-name "Intune Portal Admin" --sign-in-audience AzureADMyOrg \
    --web-redirect-uris "$URL/.auth/login/aad/callback" --enable-id-token-issuance true --query appId -o tsv)
  az ad sp create --id "$ADMIN_APP_ID" -o none
fi
ADMIN_SECRET=$(az ad app credential reset --id "$ADMIN_APP_ID" --display-name "easyauth" --years 1 --append --query password -o tsv)

az config set extension.use_dynamic_install=yes_without_prompt -o none
az webapp auth config-version upgrade -g "$RG" -n "$APP" -o none 2>/dev/null || true
az webapp auth microsoft update -g "$RG" -n "$APP" --client-id "$ADMIN_APP_ID" --client-secret "$ADMIN_SECRET" \
  --issuer "https://login.microsoftonline.com/$TENANT_ID/v2.0" --yes -o none
unset ADMIN_SECRET
az webapp auth update -g "$RG" -n "$APP" --enabled true --action RedirectToLoginPage \
  --redirect-provider azureactivedirectory --excluded-paths "/onboarding/callback" -o none

TMP=$(mktemp -d)
curl -sL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" | tar xz -C "$TMP"
SRC="$TMP/intune-portal-main"; mkdir -p "$TMP/dist"
cp -r "$SRC/backend/app" "$SRC/baselines" "$TMP/dist/"; cp "$SRC/backend/requirements.txt" "$TMP/dist/"
(cd "$TMP/dist" && zip -qr ../app.zip .)
az webapp deploy -g "$RG" -n "$APP" --src-path "$TMP/app.zip" --type zip -o none
echo "=== LISTO === $URL"

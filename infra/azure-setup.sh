#!/usr/bin/env bash
# Crea todo en Azure: app de Graph multi-tenant, Web App (plan F1 gratis), identidad OIDC para GitHub
# y hace el primer despliegue. Uso en Cloud Shell (Bash):
#   SUB="<id o nombre de suscripción>" bash azure-setup.sh
set -euo pipefail

SUB="${SUB:?Define SUB con la suscripción}"
LOC="${LOC:-eastus2}"
SKU="${SKU:-F1}"                       # F1 = gratis. B1 para producción.
RG="${RG:-rg-intune-portal}"
PLAN="${PLAN:-asp-intune-portal}"
APP="${APP:-intune-portal-camilo}"     # único en todo Azure
REPO="camilorios/intune-portal"
GRAPH_ID="00000003-0000-0000-c000-000000000000"

az account set --subscription "$SUB"
TENANT_ID=$(az account show --query tenantId -o tsv)
SUB_ID=$(az account show --query id -o tsv)
URL="https://$APP.azurewebsites.net"

# 1. Recursos
az group create -n "$RG" -l "$LOC" -o none
az appservice plan create -g "$RG" -n "$PLAN" --is-linux --sku "$SKU" -o none
az webapp create -g "$RG" -p "$PLAN" -n "$APP" --runtime "PYTHON:3.12" -o none
az webapp update -g "$RG" -n "$APP" --https-only true -o none
az webapp config set -g "$RG" -n "$APP" -o none \
  --startup-file "gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 --timeout 600 app.main:app"
if [ "$SKU" != "F1" ]; then az webapp config set -g "$RG" -n "$APP" --always-on true -o none; fi

# 2. App de Graph multi-tenant (la que consienten los clientes)
GRAPH_APP_ID=$(az ad app list --display-name "Intune Portal" --query "[0].appId" -o tsv)
if [ -z "$GRAPH_APP_ID" ]; then
  GRAPH_APP_ID=$(az ad app create --display-name "Intune Portal" --sign-in-audience AzureADMultipleOrgs \
    --web-redirect-uris "$URL/onboarding/callback" "http://localhost:8000/onboarding/callback" --query appId -o tsv)
  az ad sp create --id "$GRAPH_APP_ID" -o none
fi
for P in DeviceManagementConfiguration.ReadWrite.All DeviceManagementApps.ReadWrite.All \
         DeviceManagementServiceConfig.ReadWrite.All Group.ReadWrite.All Policy.Read.All \
         Policy.ReadWrite.ConditionalAccess; do
  RID=$(az ad sp show --id "$GRAPH_ID" --query "appRoles[?value=='$P'].id | [0]" -o tsv)
  az ad app permission add --id "$GRAPH_APP_ID" --api "$GRAPH_ID" --api-permissions "$RID=Role" -o none 2>/dev/null || true
done
GRAPH_SECRET=$(az ad app credential reset --id "$GRAPH_APP_ID" --display-name "webapp" --years 1 --append --query password -o tsv)

az webapp config appsettings set -g "$RG" -n "$APP" -o none --settings \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true DATA_DIR=/home/data BASELINES_DIR=/home/site/wwwroot/baselines \
  OBJECT_PREFIX="[HK]" CLIENT_ID="$GRAPH_APP_ID" CLIENT_SECRET="$GRAPH_SECRET" \
  REDIRECT_URI="$URL/onboarding/callback"
unset GRAPH_SECRET

# 3. Identidad OIDC para GitHub Actions
GH_APP_ID=$(az ad app list --display-name "gh-intune-portal-deploy" --query "[0].appId" -o tsv)
if [ -z "$GH_APP_ID" ]; then
  GH_APP_ID=$(az ad app create --display-name "gh-intune-portal-deploy" --query appId -o tsv)
  az ad sp create --id "$GH_APP_ID" -o none
  az ad app federated-credential create --id "$GH_APP_ID" -o none --parameters "{
    \"name\": \"github-main\", \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:$REPO:ref:refs/heads/main\", \"audiences\": [\"api://AzureADTokenExchange\"] }"
  sleep 20
fi
az role assignment create --assignee "$GH_APP_ID" --role "Website Contributor" \
  --scope "$(az webapp show -g "$RG" -n "$APP" --query id -o tsv)" -o none

# 4. Primer despliegue
TMP=$(mktemp -d)
curl -sL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" | tar xz -C "$TMP"
SRC="$TMP/intune-portal-main"; mkdir -p "$TMP/dist"
cp -r "$SRC/backend/app" "$SRC/baselines" "$TMP/dist/"; cp "$SRC/backend/requirements.txt" "$TMP/dist/"
(cd "$TMP/dist" && zip -qr ../app.zip .)
az webapp deploy -g "$RG" -n "$APP" --src-path "$TMP/app.zip" --type zip -o none

echo "=== LISTO ==="
echo "URL: $URL/docs"
echo "GRAPH CLIENT_ID: $GRAPH_APP_ID"
echo "GitHub Secret AZURE_CLIENT_ID=$GH_APP_ID"
echo "GitHub Secret AZURE_TENANT_ID=$TENANT_ID"
echo "GitHub Secret AZURE_SUBSCRIPTION_ID=$SUB_ID"
echo "GitHub Variable AZURE_WEBAPP_NAME=$APP"

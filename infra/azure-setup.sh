#!/usr/bin/env bash
# Crea la Web App y la identidad OIDC para GitHub Actions. Requiere az CLI con sesión iniciada (az login).
set -euo pipefail

SUB="<id-o-nombre-de-tu-suscripcion>"
LOC="eastus2"
RG="rg-intune-portal"
PLAN="asp-intune-portal"
APP="intune-portal-camilo"          # debe ser único en todo Azure
REPO="camilorios/intune-portal"
ENTRA_CLIENT_ID="<client-id-de-la-app-multitenant-de-graph>"

az account set --subscription "$SUB"
TENANT_ID=$(az account show --query tenantId -o tsv)
SUB_ID=$(az account show --query id -o tsv)

# 1. Recursos
az group create -n "$RG" -l "$LOC"
az appservice plan create -g "$RG" -n "$PLAN" --is-linux --sku B1
az webapp create -g "$RG" -p "$PLAN" -n "$APP" --runtime "PYTHON:3.12"
az webapp update -g "$RG" -n "$APP" --https-only true
az webapp config set -g "$RG" -n "$APP" --always-on true \
  --startup-file "gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 --timeout 600 app.main:app"
az webapp config appsettings set -g "$RG" -n "$APP" --settings \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true \
  DATA_DIR=/home/data \
  BASELINES_DIR=/home/site/wwwroot/baselines \
  OBJECT_PREFIX="[HK]" \
  CLIENT_ID="$ENTRA_CLIENT_ID" \
  REDIRECT_URI="https://$APP.azurewebsites.net/onboarding/callback"
# CLIENT_SECRET: agrégalo en el portal (Configuración > Variables de entorno) o como referencia a Key Vault.

# 2. Identidad para GitHub Actions (OIDC, sin secretos)
GH_APP_ID=$(az ad app create --display-name "gh-intune-portal-deploy" --query appId -o tsv)
az ad sp create --id "$GH_APP_ID" >/dev/null
az ad app federated-credential create --id "$GH_APP_ID" --parameters "{
  \"name\": \"github-main\",
  \"issuer\": \"https://token.actions.githubusercontent.com\",
  \"subject\": \"repo:$REPO:ref:refs/heads/main\",
  \"audiences\": [\"api://AzureADTokenExchange\"]
}"
az role assignment create --assignee "$GH_APP_ID" --role "Website Contributor" \
  --scope "$(az webapp show -g "$RG" -n "$APP" --query id -o tsv)"

echo "Configura en GitHub (Settings > Secrets and variables > Actions):"
echo "  Secret   AZURE_CLIENT_ID       = $GH_APP_ID"
echo "  Secret   AZURE_TENANT_ID       = $TENANT_ID"
echo "  Secret   AZURE_SUBSCRIPTION_ID = $SUB_ID"
echo "  Variable AZURE_WEBAPP_NAME     = $APP"
echo "Y agrega https://$APP.azurewebsites.net/onboarding/callback como Redirect URI de la app de Entra ID."

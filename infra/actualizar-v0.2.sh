#!/usr/bin/env bash
# Actualiza el portal a la v0.2 (grupos, filtros, acceso condicional, desviaciones, reset modo 2,
# backups cifrados). Uso en Cloud Shell:
#   SUB=2c212d08-1049-43db-92c7-1ea156fb98b9 RG=rg-intune-portal-westus3 APP=intune-portal-camilo bash actualizar-v0.2.sh
set -euo pipefail
SUB="${SUB:?}"; RG="${RG:?}"; APP="${APP:?}"; REPO="camilorios/intune-portal"
GRAPH_ID="00000003-0000-0000-c000-000000000000"
az account set --subscription "$SUB"

# 1. Permiso nuevo para crear acceso condicional con permisos de aplicación
GRAPH_APP_ID=$(az ad app list --display-name "Intune Portal" --query "[0].appId" -o tsv)
RID=$(az ad sp show --id "$GRAPH_ID" --query "appRoles[?value=='Application.Read.All'].id | [0]" -o tsv)
az ad app permission add --id "$GRAPH_APP_ID" --api "$GRAPH_ID" --api-permissions "$RID=Role" -o none 2>/dev/null || true
# Los clientes ya dados de alta deben volver a abrir el enlace de alta para consentir el permiso nuevo

# 2. Clave de cifrado de backups (solo si no existe: cambiarla dejaría ilegibles los backups anteriores)
HAS_KEY=$(az webapp config appsettings list -g "$RG" -n "$APP" --query "[?name=='BACKUP_KEY'] | length(@)" -o tsv)
if [ "$HAS_KEY" = "0" ]; then
  az webapp config appsettings set -g "$RG" -n "$APP" -o none --settings \
    BACKUP_KEY="$(head -c 32 /dev/urandom | base64)" SCM_DO_BUILD_DURING_DEPLOYMENT=true
  echo "BACKUP_KEY creada. Guárdala también en un lugar seguro (sin ella no se leen los backups)."
fi

# 3. Desplegar el código de la rama main
TMP=$(mktemp -d)
curl -sL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" | tar xz -C "$TMP"
SRC="$TMP/intune-portal-main"; mkdir -p "$TMP/dist"
cp -r "$SRC/backend/app" "$SRC/baselines" "$TMP/dist/"; cp "$SRC/backend/requirements.txt" "$TMP/dist/"
(cd "$TMP/dist" && zip -qr ../app.zip .)
az webapp deploy -g "$RG" -n "$APP" --src-path "$TMP/app.zip" --type zip -o none
echo "=== LISTO === https://$APP.azurewebsites.net"

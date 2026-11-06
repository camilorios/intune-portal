# Portal Intune multi-tenant — Fase 1 (MVP backend)

Incluye: onboarding por consentimiento de administrador, backup completo a JSON, vista previa,
despliegue de baselines con snapshot previo y reversión de un despliegue (modo 1 del reset).

## 1. Registrar la app en TU tenant (Entra ID)
1. Entra ID > App registrations > New registration
   - Supported account types: **Accounts in any organizational directory (Multitenant)**
   - Redirect URI (Web): `http://localhost:8000/onboarding/callback`
2. API permissions > Microsoft Graph > **Application permissions**:
   - DeviceManagementConfiguration.ReadWrite.All
   - DeviceManagementApps.ReadWrite.All
   - DeviceManagementServiceConfig.ReadWrite.All
   - Group.ReadWrite.All
   - Policy.Read.All, Policy.ReadWrite.ConditionalAccess
3. Certificates & secrets > New client secret (solo desarrollo; en producción usar certificado en Key Vault).
4. Copia `.env.example` a `.env` y llena CLIENT_ID y CLIENT_SECRET.

## 2. Ejecutar
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend && cp ../.env.example .env  # y edítalo
DATA_DIR=../data BASELINES_DIR=../baselines uvicorn app.main:app --reload
```
Abre http://localhost:8000/docs

## 3. Probar con un tenant de pruebas
1. GET `/onboarding/consent-url` y abre el enlace con el admin global del tenant de pruebas.
2. Tras aceptar, el callback registra el tenant.
3. POST `/tenants/{id}/backup`
4. GET `/tenants/{id}/preview/pyme-windows-v1`
5. POST `/tenants/{id}/deploy` con `{"baseline":"pyme-windows-v1","confirm_tenant":"{id}"}`
6. POST `/tenants/{id}/rollback` con el `deployment_id` devuelto.

## Estructura
- `backend/app/graph.py`: cliente Graph por tenant con reintentos por throttling (429).
- `backend/app/resources.py`: tipos de objetos Intune y orden para el reset.
- `backend/app/backup.py`, `deploy.py`: backup, vista previa, despliegue, reversión.
- `baselines/<nombre>/*.json`: cada archivo = un objeto a crear.
- `data/`: tenants, backups, despliegues y auditoría (MVP en archivos; luego PostgreSQL).

## Siguiente
- Login Entra ID para técnicos y roles.
- Frontend React.
- Modos 2 y 3 del restablecimiento (quitar lo del portal, reset total).

## Despliegue desde GitHub (Azure Container Apps)
Cada push a `main` construye la imagen en GHCR y, si configuraste las variables, la despliega.

1. Crea en Azure un Resource Group y una Container App (puerto 8000).
2. En la Container App configura las variables CLIENT_ID, REDIRECT_URI y el secreto CLIENT_SECRET
   (o mejor, referencia a Key Vault). Agrega la URL pública `/onboarding/callback` como Redirect URI de la app de Entra ID.
3. Crea una identidad para GitHub Actions con credencial federada (OIDC) para este repo, rama `main`,
   con rol Contributor sobre el Resource Group.
4. En GitHub > Settings > Secrets and variables > Actions:
   - Secrets: AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID, GHCR_PULL_TOKEN (PAT con read:packages)
   - Variables: AZURE_CONTAINERAPP_NAME, AZURE_RESOURCE_GROUP

Nota: `data/` en el contenedor es efímero; en la fase 2 se reemplaza por PostgreSQL / Azure Files.

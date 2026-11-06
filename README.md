# Portal Intune multi-tenant — v0.2

Incluye: onboarding por consentimiento de administrador, backup completo y cifrado (AES-256-GCM),
vista previa, despliegue de baselines (omitir o actualizar lo existente) con snapshot previo,
grupos dinámicos y filtros con asignaciones por nombre (tabla de migración por tenant),
acceso condicional en modo solo informe con grupo de emergencia excluido, detección de
desviaciones por propiedad con restauración, y restablecimiento modos 1 (revertir un despliegue)
y 2 (quitar todo lo [HK]). El portal nunca ejecuta acciones sobre dispositivos.

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
- `backend/app/resources.py`: catálogo de tipos (endpoint, orden de importación, propiedades de solo lectura).
- `backend/app/backup.py`: backup de todos los tipos con sus asignaciones.
- `backend/app/deploy.py`: vista previa, despliegue (skip/update), referencias `@group:` / `@filter:`, reversión.
- `backend/app/drift.py`: desviaciones por propiedad y restauración.
- `backend/app/reset.py`: modo 2 del restablecimiento.
- `backend/tests/`: flujo completo contra un Graph falso (`cd backend && python -m pytest -q`).
- `baselines/<nombre>/`: `_baseline.json` (título, descripción, fuente) y un JSON por objeto.
- `scripts/import_hydration_kit.py`: regenera las baselines basadas en Intune Hydration Kit (MIT).
- `data/`: tenants, backups, despliegues y auditoría (MVP en archivos; luego PostgreSQL).

## Formato de un objeto de baseline
```json
{
  "resource": "compliance",
  "assign": {"groups": ["Intune - iOS iPadOS Devices"], "filter": {"name": "Windows - Physical Devices Only", "mode": "include"}},
  "body": {"@odata.type": "#microsoft.graph.iosCompliancePolicy", "displayName": "iOS Compliance"}
}
```
`assign` admite `allDevices`, `allUsers`, `groups`, `excludeGroups` y `filter`. Dentro de `body`,
`"@group:Nombre"` y `"@filter:Nombre"` se sustituyen por el ID real en el tenant del cliente.

## Baselines incluidas
| Baseline | Contenido |
|---|---|
| `grupos-y-filtros-v1` | 8 grupos dinámicos (SO, Autopilot, corporativo/BYOD) y 12 filtros de VM y Cloud PC. Desplegar primero. |
| `identidad-segura-v1` | 7 políticas de acceso condicional (MFA admins, portales, Azure, usuarios, invitados; bloqueo de autenticación heredada; registro de MFA) en solo informe + grupo de emergencia. Requiere Entra ID P1. |
| `moviles-v1` | Cumplimiento iOS/Android y protección de apps nivel 2 para iOS y Android. |
| `pyme-windows-v1` | Cumplimiento y restricciones de Windows para todos los dispositivos. |

## Siguiente
- Roles de técnicos (lector, operador, administrador) y modo 3 del reset.
- Informe del tenant en HTML/PDF con la marca de JCRsystem.
- Key Vault con certificado en lugar de client secret.

## Despliegue desde GitHub (Azure App Service)
Cada push a `main` empaqueta la app y la despliega a una Web App Linux (Python 3.12) por OIDC.
Ver `infra/azure-setup.sh` para crear los recursos. Luego en GitHub > Settings > Secrets and variables > Actions:
- Secrets: AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID
- Variable: AZURE_WEBAPP_NAME

Datos: `DATA_DIR=/home/data` (almacenamiento persistente de App Service) hasta migrar a PostgreSQL.

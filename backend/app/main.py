import json
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import store
from .backup import take_backup
from .config import settings
from .deploy import deploy, preview, rollback

app = FastAPI(title="Portal Intune multi-tenant", version="0.1.0")
# Autenticación: App Service Authentication (Easy Auth) con Entra ID protege todo el sitio,
# excepto /onboarding/callback (lo abre el admin del cliente). El usuario llega en el header
# X-MS-CLIENT-PRINCIPAL-NAME y se registra en la auditoría.
STATIC = Path(__file__).parent / "static"


def user_of(request: Request) -> str:
    return request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME", "local-dev")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/me")
def me(request: Request):
    return {"user": user_of(request)}


@app.get("/baselines")
def list_baselines():
    root = Path(settings.baselines_dir)
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        items = [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))]
        out.append({"name": d.name, "items": [{"resource": i["resource"], "name": i["body"].get("displayName") or i["body"].get("name")} for i in items]})
    return out


@app.get("/onboarding/consent-url")
def consent_url():
    """Enlace que se envía al administrador global del cliente."""
    q = urlencode({"client_id": settings.client_id, "redirect_uri": settings.redirect_uri})
    return {"url": f"https://login.microsoftonline.com/organizations/adminconsent?{q}"}


@app.get("/onboarding/callback")
def consent_callback(tenant: str, admin_consent: str = "False", error: str | None = None, error_description: str | None = None):
    if error or admin_consent.lower() != "true":
        raise HTTPException(400, f"Consentimiento no otorgado: {error_description or error}")
    store.add_tenant(tenant, name=tenant)
    store.audit(tenant, "onboarded", {})
    return {"ok": True, "tenant": tenant, "mensaje": "Tenant registrado. Puede tardar unos minutos en propagarse el permiso."}


@app.get("/tenants")
def list_tenants():
    return store.tenants()


def _check(tenant_id: str):
    if tenant_id not in store.tenants():
        raise HTTPException(404, "Tenant no registrado")


@app.post("/tenants/{tenant_id}/backup")
def backup(tenant_id: str, request: Request):
    _check(tenant_id)
    store.audit(tenant_id, "backup_requested", {"user": user_of(request)})
    return {"backup_id": take_backup(tenant_id, "manual")}


@app.get("/tenants/{tenant_id}/deployments")
def list_deployments(tenant_id: str):
    _check(tenant_id)
    return store.list_records("deployments", tenant_id)


@app.get("/tenants/{tenant_id}/preview/{baseline}")
def do_preview(tenant_id: str, baseline: str):
    _check(tenant_id)
    return preview(tenant_id, baseline)


class DeployRequest(BaseModel):
    baseline: str
    confirm_tenant: str  # el técnico escribe el tenant id para confirmar


@app.post("/tenants/{tenant_id}/deploy")
def do_deploy(tenant_id: str, req: DeployRequest, request: Request):
    _check(tenant_id)
    if req.confirm_tenant != tenant_id:
        raise HTTPException(400, "La confirmación no coincide con el tenant")
    store.audit(tenant_id, "deploy_requested", {"user": user_of(request), "baseline": req.baseline})
    return deploy(tenant_id, req.baseline)


class RollbackRequest(BaseModel):
    deployment_id: str
    confirm_tenant: str


@app.post("/tenants/{tenant_id}/rollback")
def do_rollback(tenant_id: str, req: RollbackRequest, request: Request):
    _check(tenant_id)
    if req.confirm_tenant != tenant_id:
        raise HTTPException(400, "La confirmación no coincide con el tenant")
    store.audit(tenant_id, "rollback_requested", {"user": user_of(request), "deployment_id": req.deployment_id})
    return rollback(tenant_id, req.deployment_id)

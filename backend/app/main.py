import json
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import store
from .backup import take_backup
from .config import settings
from . import drift, reset
from .deploy import baseline_meta, deploy, load_baseline, plan, rollback
from .resources import RESOURCES, get

app = FastAPI(title="Portal Intune multi-tenant", version="0.2.0")
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
        items = load_baseline(d.name)
        out.append({"name": d.name, **baseline_meta(d.name),
                    "items": [{"resource": i["resource"], "type": get(i["resource"])["title"],
                               "name": i["body"].get("displayName") or i["body"].get("name"),
                               "assign": i.get("assign")} for i in items]})
    return out


@app.get("/resources")
def list_resources():
    """Catálogo de tipos que el portal respalda y despliega."""
    return [{"key": r["key"], "title": r["title"], "deploy": not r.get("readonly_deploy")} for r in RESOURCES]


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


@app.get("/tenants/{tenant_id}/audit")
def list_audit(tenant_id: str):
    _check(tenant_id)
    return store.read_audit(tenant_id)


@app.get("/tenants/{tenant_id}/backups")
def list_backups(tenant_id: str):
    _check(tenant_id)
    return store.list_records("backups", tenant_id)


@app.get("/tenants/{tenant_id}/preview/{baseline}")
def do_preview(tenant_id: str, baseline: str, mode: str = "skip"):
    _check(tenant_id)
    try:
        return plan(tenant_id, baseline, mode)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))


class Confirmed(BaseModel):
    confirm_tenant: str  # el técnico escribe el tenant id para confirmar


def _confirm(tenant_id: str, req: Confirmed):
    _check(tenant_id)
    if req.confirm_tenant.strip() != tenant_id:
        raise HTTPException(400, "La confirmación no coincide con el tenant")


class DeployRequest(Confirmed):
    baseline: str
    mode: str = "skip"  # skip: no toca lo existente · update: actualiza lo existente a la baseline


@app.post("/tenants/{tenant_id}/deploy")
def do_deploy(tenant_id: str, req: DeployRequest, request: Request):
    _confirm(tenant_id, req)
    store.audit(tenant_id, "deploy_requested", {"user": user_of(request), "baseline": req.baseline, "mode": req.mode})
    return deploy(tenant_id, req.baseline, req.mode, user_of(request))


class RollbackRequest(Confirmed):
    deployment_id: str


@app.post("/tenants/{tenant_id}/rollback")
def do_rollback(tenant_id: str, req: RollbackRequest, request: Request):
    _confirm(tenant_id, req)
    store.audit(tenant_id, "rollback_requested", {"user": user_of(request), "deployment_id": req.deployment_id})
    return rollback(tenant_id, req.deployment_id, user_of(request))


@app.get("/tenants/{tenant_id}/drift/{baseline}")
def do_drift(tenant_id: str, baseline: str):
    _check(tenant_id)
    return drift.check(tenant_id, baseline)


class RestoreRequest(Confirmed):
    baseline: str


@app.post("/tenants/{tenant_id}/drift/restore")
def do_restore(tenant_id: str, req: RestoreRequest, request: Request):
    _confirm(tenant_id, req)
    return drift.restore(tenant_id, req.baseline, user_of(request))


@app.get("/tenants/{tenant_id}/reset/owned")
def reset_preview(tenant_id: str):
    _check(tenant_id)
    return reset.preview(tenant_id)


@app.post("/tenants/{tenant_id}/reset/owned")
def reset_owned(tenant_id: str, req: Confirmed, request: Request):
    _confirm(tenant_id, req)
    store.audit(tenant_id, "reset_owned_requested", {"user": user_of(request)})
    return reset.remove_owned(tenant_id, user_of(request))

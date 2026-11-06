"""Backup completo del tenant: todos los tipos del catálogo, con sus asignaciones cuando Graph lo permite."""
from . import store
from .graph import GraphClient
from .resources import RESOURCES


def _query(r: dict) -> str:
    expands = [x for x in (r.get("expand"), "assignments" if r.get("assign") else None) if x]
    q = r.get("list_filter", "")
    if expands:
        q = "&".join(x for x in (q, "$expand=" + ",".join(expands)) if x)
    return q


def snapshot_objects(g: GraphClient) -> dict:
    objects = {}
    for r in RESOURCES:
        try:
            objects[r["key"]] = g.list_all(r["path"], r["version"], _query(r))
        except RuntimeError:
            try:  # algunos tipos no admiten $expand: segundo intento sin él
                objects[r["key"]] = g.list_all(r["path"], r["version"], r.get("list_filter", ""))
            except RuntimeError as e:  # p.ej. tenant sin licencia para un tipo
                objects[r["key"]] = {"error": str(e)[:500]}
    return objects


def take_backup(tenant_id: str, reason: str) -> str:
    g = GraphClient(tenant_id)
    data = {"tenant": tenant_id, "reason": reason, "at": store.now(), "objects": snapshot_objects(g)}
    rid = store.save("backups", tenant_id, data)
    store.audit(tenant_id, "backup", {"backup_id": rid, "reason": reason})
    return rid

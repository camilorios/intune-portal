from . import store
from .graph import GraphClient
from .resources import RESOURCES


def take_backup(tenant_id: str, reason: str) -> str:
    g = GraphClient(tenant_id)
    data = {"tenant": tenant_id, "reason": reason, "at": store.now(), "objects": {}}
    for r in RESOURCES:
        try:
            data["objects"][r["key"]] = g.list_all(r["path"], r["version"])
        except RuntimeError as e:  # p.ej. tenant sin licencia para un tipo
            data["objects"][r["key"]] = {"error": str(e)}
    rid = store.save("backups", tenant_id, data)
    store.audit(tenant_id, "backup", {"backup_id": rid, "reason": reason})
    return rid

"""Modo 2 del restablecimiento: quitar del tenant todo lo creado por el portal (prefijo [HK]).

Solo toca objetos cuyo nombre empieza con el prefijo del portal: lo que el cliente creó
por su cuenta nunca se elimina. Orden seguro: acceso condicional → políticas → apps →
filtros → grupos. Eliminar una política elimina también sus asignaciones.
Nunca se ejecutan acciones sobre dispositivos (wipe, retire).
"""
from . import store
from .backup import take_backup
from .config import settings
from .graph import GraphClient
from .resources import delete_order, name_of


def owned_objects(g: GraphClient) -> list[dict]:
    out = []
    for res in delete_order():
        try:
            objs = g.list_all(res["path"], res["version"], res.get("list_filter", ""))
        except RuntimeError:
            continue  # tipo no disponible en el tenant
        for o in objs:
            if name_of(res, o).startswith(settings.object_prefix):
                out.append({"resource": res["key"], "type": res["title"], "id": o["id"], "name": name_of(res, o)})
    return out


def preview(tenant_id: str, g: GraphClient | None = None) -> list[dict]:
    return owned_objects(g or GraphClient(tenant_id))


def remove_owned(tenant_id: str, user: str = "", g: GraphClient | None = None) -> dict:
    from .resources import get
    g = g or GraphClient(tenant_id)
    targets = owned_objects(g)
    backup_id = take_backup(tenant_id, "antes de quitar todo lo del portal (reset modo 2)")
    removed, errors = [], []
    for o in targets:
        res = get(o["resource"])
        try:
            g.delete(f"{res['path']}/{o['id']}", res["version"])
            removed.append(o)
        except RuntimeError as e:
            errors.append({**o, "error": str(e)[:1000]})
    store.audit(tenant_id, "reset_owned", {"backup_id": backup_id, "user": user,
                                           "removed": len(removed), "errors": len(errors)})
    return {"backup_id": backup_id, "removed": removed, "errors": errors}

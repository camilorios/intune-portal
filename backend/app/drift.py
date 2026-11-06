"""Detección de desviaciones (drift) contra una baseline y restauración de los valores esperados.

Para cada objeto de la baseline busca el objeto [HK] del cliente y compara propiedad por
propiedad lo que la baseline define. Lo que el cliente cambió a mano aparece como desviación.
"""
from . import store
from .backup import take_backup
from .deploy import Inventory, desired_body, diff, load_baseline, resolve_refs, find_refs
from .graph import GraphClient
from .resources import clean_body, get, name_of


def check(tenant_id: str, baseline: str, g: GraphClient | None = None) -> list[dict]:
    g = g or GraphClient(tenant_id)
    inv, out = Inventory(g), []
    for item in load_baseline(baseline):
        res = get(item["resource"])
        if res.get("readonly_deploy"):
            continue
        body = desired_body(res, item["body"])
        name = name_of(res, body)
        row = {"resource": res["key"], "type": res["title"], "name": name, "differences": []}
        existing = inv.by_name(res).get(name)
        if not existing:
            row["status"] = "falta"
        else:
            row["id"] = existing["id"]
            table = {r: inv.lookup(*r) for r in find_refs(item["body"])}
            try:
                body = resolve_refs(body, table)
            except LookupError:
                pass
            if res.get("no_patch"):
                body = {"settings": body.get("settings", [])}
            row["differences"] = diff(res, body, inv.full(res, existing["id"]))
            row["status"] = "desviado" if row["differences"] else "ok"
        out.append(row)
    return out


def restore(tenant_id: str, baseline: str, user: str = "", g: GraphClient | None = None) -> dict:
    """Devuelve a los valores de la baseline las propiedades desviadas (no crea lo que falta)."""
    g = g or GraphClient(tenant_id)
    rows = [r for r in check(tenant_id, baseline, g) if r["status"] == "desviado"]
    backup_id = take_backup(tenant_id, f"antes de restaurar desviaciones de {baseline}")
    fixed, errors, skipped = [], [], []
    for r in rows:
        res = get(r["resource"])
        if res.get("no_patch"):
            skipped.append({"name": r["name"], "reason": "Settings Catalog: redesplegar para restaurar"})
            continue
        patch = clean_body(res, {d["property"]: d["expected"] for d in r["differences"]}, for_update=True)
        actual = g.get(f"{res['path']}/{r['id']}", res["version"])
        if "@odata.type" in actual:
            patch["@odata.type"] = actual["@odata.type"]
        try:
            g.patch(f"{res['path']}/{r['id']}", patch, res["version"])
            fixed.append({"name": r["name"], "properties": [d["property"] for d in r["differences"]]})
        except RuntimeError as e:
            errors.append({"name": r["name"], "error": str(e)[:1000]})
    store.audit(tenant_id, "drift_restore", {"baseline": baseline, "backup_id": backup_id, "user": user,
                                             "fixed": len(fixed), "errors": len(errors)})
    return {"backup_id": backup_id, "fixed": fixed, "skipped": skipped, "errors": errors}

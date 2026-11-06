"""Vista previa, despliegue, actualización y reversión de baselines.

Formato de cada archivo de una baseline (los que empiezan por "_" son metadatos):
{
  "resource": "<clave del catálogo>",
  "body": { ...objeto de Graph... },
  "assign": {                      # opcional
    "allDevices": true | "allUsers": true,
    "groups": ["Nombre de grupo"], "excludeGroups": ["Otro grupo"],
    "filter": {"name": "Nombre del filtro", "mode": "include" | "exclude"}
  }
}
Dentro de "body" se puede referenciar un grupo o filtro por nombre con "@group:Nombre" o
"@filter:Nombre"; al desplegar se traduce al ID real del tenant del cliente (tabla de migración,
idea de IntuneManagement). Los nombres se buscan primero con el prefijo del portal.
"""
import copy
import json
import re
from pathlib import Path

from . import store
from .backup import take_backup
from .config import settings
from .graph import GraphClient
from .resources import clean_body, get, name_of

MODES = {"skip", "update"}
TARGETS = {
    "allDevices": "#microsoft.graph.allDevicesAssignmentTarget",
    "allUsers": "#microsoft.graph.allLicensedUsersAssignmentTarget",
    "group": "#microsoft.graph.groupAssignmentTarget",
    "exclude": "#microsoft.graph.exclusionGroupAssignmentTarget",
}
DEVICE_ACTIONS = {"retire", "wipe", "remoteLock", "removeResourceAccessProfiles"}
REF = re.compile(r"^@(group|filter):(.+)$")


# ---------- baselines ----------
def baseline_dir(name: str) -> Path:
    if not re.fullmatch(r"[\w.-]+", name):
        raise FileNotFoundError("Nombre de baseline inválido")
    folder = Path(settings.baselines_dir) / name
    if not folder.is_dir():
        raise FileNotFoundError(f"Baseline {name} no existe")
    return folder


def load_baseline(name: str) -> list[dict]:
    items = [json.loads(f.read_text()) for f in sorted(baseline_dir(name).glob("*.json")) if not f.name.startswith("_")]
    for it in items:  # compatibilidad con el formato anterior
        if it.pop("assignAllDevices", False) and "assign" not in it:
            it["assign"] = {"allDevices": True}
    return sorted(items, key=lambda it: get(it["resource"])["import_order"])


def baseline_meta(name: str) -> dict:
    p = baseline_dir(name) / "_baseline.json"
    return json.loads(p.read_text()) if p.exists() else {}


# ---------- normalización ----------
def prefixed_name(name: str) -> str:
    return name if name.startswith(settings.object_prefix) else f"{settings.object_prefix} {name}".strip()


def desired_body(res: dict, body: dict) -> dict:
    """Cuerpo final que se envía a Graph: limpio, con prefijo y reglas de seguridad del portal."""
    b = clean_body(res, copy.deepcopy(body))
    field = res.get("name_field", "displayName")
    b[field] = prefixed_name(b.get(field, ""))
    if res["key"] == "conditionalAccess" and b.get("state") != "disabled":
        b["state"] = settings.ca_state  # nunca se aplica en modo forzado sin revisión (idea de Hydration Kit)
    if res["key"] == "compliance":
        # Regla del portal: nunca acciones sobre dispositivos (retirar, borrar, bloquear remoto)
        for rule in b.get("scheduledActionsForRule", []):
            rule["scheduledActionConfigurations"] = [
                a for a in rule.get("scheduledActionConfigurations", []) if a.get("actionType") not in DEVICE_ACTIONS]
    if res["key"] == "groups":
        if b.get("membershipRule"):
            b.setdefault("groupTypes", ["DynamicMembership"])
            b.setdefault("membershipRuleProcessingState", "On")
        b.setdefault("groupTypes", [])
        b.setdefault("securityEnabled", True)
        b.setdefault("mailEnabled", False)
        b.setdefault("mailNickname", re.sub(r"[^A-Za-z0-9]", "", b["displayName"])[:56] or "hkgroup")
    return b


def find_refs(v, out=None) -> set:
    out = set() if out is None else out
    if isinstance(v, str) and REF.match(v):
        out.add(REF.match(v).groups())
    elif isinstance(v, dict):
        for x in v.values():
            find_refs(x, out)
    elif isinstance(v, list):
        for x in v:
            find_refs(x, out)
    return out


def resolve_refs(v, table: dict):
    if isinstance(v, str) and REF.match(v):
        kind, name = REF.match(v).groups()
        if (kind, name) not in table:
            raise LookupError(f"No existe el {'grupo' if kind == 'group' else 'filtro'} «{name}» en el tenant")
        return table[(kind, name)]
    if isinstance(v, dict):
        return {k: resolve_refs(x, table) for k, x in v.items()}
    if isinstance(v, list):
        return [resolve_refs(x, table) for x in v]
    return v


def assign_refs(assign: dict | None) -> set:
    a = assign or {}
    refs = {("group", n) for n in a.get("groups", []) + a.get("excludeGroups", [])}
    if a.get("filter"):
        refs.add(("filter", a["filter"]["name"]))
    return refs


def build_assignments(res: dict, assign: dict, table: dict) -> list[dict]:
    a, out = assign or {}, []
    flt = {}
    if a.get("filter"):
        flt = {"deviceAndAppManagementAssignmentFilterId": table[("filter", a["filter"]["name"])],
               "deviceAndAppManagementAssignmentFilterType": a["filter"].get("mode", "include")}
    if a.get("allDevices"):
        if res.get("assign_users"):
            raise ValueError(f"{res['title']} se asigna a usuarios, no a dispositivos (usa allUsers)")
        out.append({"target": {"@odata.type": TARGETS["allDevices"], **flt}})
    if a.get("allUsers"):
        out.append({"target": {"@odata.type": TARGETS["allUsers"], **flt}})
    for n in a.get("groups", []):
        out.append({"target": {"@odata.type": TARGETS["group"], "groupId": table[("group", n)], **flt}})
    for n in a.get("excludeGroups", []):
        out.append({"target": {"@odata.type": TARGETS["exclude"], "groupId": table[("group", n)]}})
    return out


# ---------- comparación ----------
def same(a, b) -> bool:
    if a in (None, [], {}, "") and b in (None, [], {}, ""):
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        return all(same(v, b.get(k)) for k, v in a.items() if "@odata" not in k or k == "@odata.type")
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, str) and isinstance(b, str):
        return a.lower() == b.lower() if a.startswith("#microsoft") else a == b
    return a == b


def diff(res: dict, desired: dict, actual: dict) -> list[dict]:
    """Propiedades de la baseline cuyo valor en el tenant es distinto (diff por propiedad, idea de TrustM365)."""
    skip = {res.get("name_field", "displayName"), "@odata.type"} | res.get("remove_update", set())
    return [{"property": k, "expected": v, "actual": actual.get(k)}
            for k, v in desired.items() if k not in skip and not same(v, actual.get(k))]


class Inventory:
    """Objetos existentes del tenant por tipo, cargados una sola vez por operación."""

    def __init__(self, g: GraphClient):
        self.g, self._cache = g, {}

    def by_name(self, res: dict) -> dict:
        if res["key"] not in self._cache:
            objs = self.g.list_all(res["path"], res["version"], res.get("list_filter", ""))
            self._cache[res["key"]] = {name_of(res, o): o for o in objs}
        return self._cache[res["key"]]

    def lookup(self, kind: str, name: str):
        res = get("groups" if kind == "group" else "assignmentFilters")
        objs = self.by_name(res)
        o = objs.get(prefixed_name(name)) or objs.get(name)
        return o["id"] if o else None

    def full(self, res: dict, obj_id: str) -> dict:
        q = f"?$expand={res['expand']}" if res.get("expand") else ""
        return self.g.get(f"{res['path']}/{obj_id}{q}", res["version"])


# ---------- vista previa ----------
def plan(tenant_id: str, baseline: str, mode: str = "skip", g: GraphClient | None = None) -> list[dict]:
    if mode not in MODES:
        raise ValueError("Modo inválido")
    g = g or GraphClient(tenant_id)
    inv, steps = Inventory(g), []
    # Grupos y filtros que la propia baseline va a crear, para resolver referencias en la vista previa
    planned = {("group" if get(i["resource"])["key"] == "groups" else "filter", i["body"].get("displayName"))
               for i in load_baseline(baseline) if get(i["resource"])["key"] in ("groups", "assignmentFilters")}
    for item in load_baseline(baseline):
        res = get(item["resource"])
        body = desired_body(res, item["body"])
        name = name_of(res, body)
        step = {"resource": res["key"], "type": res["title"], "name": name, "changes": []}
        missing = [f"{k}: {n}" for k, n in find_refs(item["body"]) | assign_refs(item.get("assign"))
                   if (k, n) not in planned and not inv.lookup(k, n)]
        existing = inv.by_name(res).get(name)
        if res.get("readonly_deploy"):
            step["action"] = "no soportado (solo backup)"
        elif missing:
            step["action"] = "error: falta " + ", ".join(missing)
        elif not existing:
            step["action"] = "create"
        elif mode == "skip":
            step["action"] = "skip (ya existe)"
        elif res.get("no_patch"):
            step["action"] = "skip (este tipo no admite actualización)"
        else:
            changes = diff(res, body, inv.full(res, existing["id"]))
            step["changes"] = [c["property"] for c in changes]
            step["action"] = "update" if changes else "sin cambios"
        steps.append(step)
    return steps


# ---------- despliegue ----------
def deploy(tenant_id: str, baseline: str, mode: str = "skip", user: str = "", g: GraphClient | None = None) -> dict:
    g = g or GraphClient(tenant_id)
    steps = {(s["resource"], s["name"]): s for s in plan(tenant_id, baseline, mode, g)}
    snapshot = take_backup(tenant_id, f"antes de desplegar {baseline}")
    inv = Inventory(g)
    table, created, updated, errors, skipped = {}, [], [], [], []

    def ref_table(item):
        for kind, n in find_refs(item["body"]) | assign_refs(item.get("assign")):
            if (kind, n) not in table:
                found = inv.lookup(kind, n)
                if found:
                    table[(kind, n)] = found

    for item in load_baseline(baseline):
        res = get(item["resource"])
        step = steps[(res["key"], name_of(res, desired_body(res, item["body"])))]
        name = step["name"]
        try:
            ref_table(item)
            body = resolve_refs(desired_body(res, item["body"]), table)
            if step["action"] == "create":
                obj = g.create(res["path"], body, res["version"])
                created.append({"resource": res["key"], "id": obj["id"], "name": name})
                _assign(g, res, obj["id"], item.get("assign"), table)
                obj_id = obj["id"]
            elif step["action"] == "update":
                obj_id = inv.by_name(res)[name]["id"]
                before = inv.full(res, obj_id)
                patch = clean_body(res, body, for_update=True)
                if "@odata.type" in before:
                    patch["@odata.type"] = before["@odata.type"]
                g.patch(f"{res['path']}/{obj_id}", patch, res["version"])
                updated.append({"resource": res["key"], "id": obj_id, "name": name, "changes": step["changes"],
                                "before": {k: before.get(k) for k in step["changes"]} | (
                                    {"@odata.type": before["@odata.type"]} if "@odata.type" in before else {})})
            else:
                skipped.append({"resource": res["key"], "name": name, "reason": step["action"]})
                existing = inv.by_name(res).get(name)
                obj_id = existing["id"] if existing else None
            # Los grupos/filtros quedan disponibles para los siguientes objetos de la baseline
            if res["key"] in ("groups", "assignmentFilters") and obj_id:
                table[("group" if res["key"] == "groups" else "filter", item["body"].get("displayName"))] = obj_id
        except (RuntimeError, LookupError, ValueError) as e:
            errors.append({"resource": res["key"], "name": name, "error": str(e)[:1000]})

    record = {"baseline": baseline, "mode": mode, "user": user, "snapshot": snapshot, "created": created,
              "updated": updated, "skipped": skipped, "errors": errors,
              "migration_table": {f"{k}:{n}": v for (k, n), v in table.items()}, "at": store.now()}
    rid = store.save("deployments", tenant_id, record)
    store.audit(tenant_id, "deploy", {"deployment_id": rid, "baseline": baseline, "mode": mode, "user": user,
                                      "created": len(created), "updated": len(updated), "errors": len(errors)})
    return {"deployment_id": rid, **record}


def _assign(g: GraphClient, res: dict, obj_id: str, assign: dict | None, table: dict) -> None:
    if not assign or not res.get("assign"):
        return
    assignments = build_assignments(res, assign, table)
    if not assignments:
        return
    if res["key"] == "autopilotProfiles":  # Autopilot no tiene acción /assign: una a una
        for a in assignments:
            g.create(f"{res['path']}/{obj_id}/assignments", a, res["version"])
    elif res["key"] == "enrollmentConfigurations":
        g.create(f"{res['path']}/{obj_id}/assign", {"enrollmentConfigurationAssignments": assignments}, res["version"])
    else:
        g.create(f"{res['path']}/{obj_id}/assign", {"assignments": assignments}, res["version"])


def rollback(tenant_id: str, deployment_id: str, user: str = "", g: GraphClient | None = None) -> dict:
    """Modo 1 del restablecimiento: deshace un despliegue concreto.
    Elimina lo creado (en orden inverso) y devuelve lo actualizado a sus valores anteriores."""
    record = store.load("deployments", tenant_id, deployment_id)
    backup_id = take_backup(tenant_id, f"antes de revertir {deployment_id}")
    g = g or GraphClient(tenant_id)
    removed, restored, errors = [], [], []
    for obj in reversed(record.get("updated", [])):
        res = get(obj["resource"])
        try:
            g.patch(f"{res['path']}/{obj['id']}", obj["before"], res["version"])
            restored.append({k: obj[k] for k in ("resource", "id", "name")})
        except RuntimeError as e:
            errors.append({k: obj[k] for k in ("resource", "id", "name")} | {"error": str(e)[:1000]})
    for obj in sorted(record["created"], key=lambda o: -get(o["resource"])["import_order"]):
        res = get(obj["resource"])
        try:
            g.delete(f"{res['path']}/{obj['id']}", res["version"])
            removed.append(obj)
        except RuntimeError as e:
            errors.append({**obj, "error": str(e)[:1000]})
    store.audit(tenant_id, "rollback", {"deployment_id": deployment_id, "backup_id": backup_id, "user": user,
                                        "removed": len(removed), "restored": len(restored), "errors": len(errors)})
    return {"backup_id": backup_id, "removed": removed, "restored": restored, "errors": errors}

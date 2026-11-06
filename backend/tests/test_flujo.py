"""Pruebas del flujo completo contra un Graph falso en memoria (sin tocar ningún tenant).
Ejecutar desde backend/:  python -m pytest -q"""
import base64
import copy
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
os.environ.update(CLIENT_ID="test", CLIENT_SECRET="test", BASELINES_DIR=str(ROOT / "baselines"),
                  BACKUP_KEY=base64.b64encode(b"k" * 32).decode())
sys.path.insert(0, str(ROOT / "backend"))

T = "11111111-1111-1111-1111-111111111111"


class FakeGraph:
    def __init__(self):
        self.objs, self.assignments, self.calls = {}, {}, []

    def _split(self, path):
        path = path.split("?")[0]
        for col in sorted(self.objs, key=len, reverse=True):
            if path.startswith(col + "/"):
                return col, path[len(col) + 1:].split("/")
        return path, []

    def list_all(self, path, version="v1.0", query=""):
        return copy.deepcopy(self.objs.get(path, []))

    def get(self, path, version="v1.0"):
        col, rest = self._split(path)
        return copy.deepcopy(next(o for o in self.objs[col] if o["id"] == rest[0]))

    def create(self, path, body, version="v1.0"):
        self.calls.append(("POST", path))
        col, rest = self._split(path)
        if rest:  # /{id}/assign o /{id}/assignments
            self.assignments.setdefault(rest[0], []).append(body)
            return {}
        assert "id" not in body and "createdDateTime" not in body
        obj = {**copy.deepcopy(body), "id": uuid.uuid4().hex}
        self.objs.setdefault(path, []).append(obj)
        return obj

    def patch(self, path, body, version="v1.0"):
        self.calls.append(("PATCH", path))
        col, rest = self._split(path)
        next(o for o in self.objs[col] if o["id"] == rest[0]).update(copy.deepcopy(body))

    def delete(self, path, version="v1.0"):
        self.calls.append(("DELETE", path))
        col, rest = self._split(path)
        self.objs[col] = [o for o in self.objs[col] if o["id"] != rest[0]]


@pytest.fixture()
def g(tmp_path, monkeypatch):
    from app import backup, config, deploy, drift, reset, store
    monkeypatch.setattr(config.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    fake = FakeGraph()
    for m in (backup, deploy, drift, reset):
        monkeypatch.setattr(m, "GraphClient", lambda tid, fake=fake: fake)
    store.add_tenant(T, "Cliente prueba")
    # Un objeto del cliente que el portal nunca debe tocar
    fake.objs["deviceManagement/deviceCompliancePolicies"] = [{"id": "cli-1", "displayName": "Política del cliente"}]
    return fake


def test_todas_las_baselines_cargan():
    from app.deploy import load_baseline
    for d in (ROOT / "baselines").iterdir():
        assert load_baseline(d.name), d.name


def test_identidad_crea_grupo_primero_y_ca_en_solo_informe(g):
    from app.deploy import deploy, plan
    p = plan(T, "identidad-segura-v1")
    assert all(s["action"] == "create" for s in p), p
    r = deploy(T, "identidad-segura-v1", "skip", "tecnico@jcr")
    assert not r["errors"], r["errors"]
    bg = g.objs["groups"][0]
    assert bg["displayName"] == "[HK] Cuentas de emergencia (break-glass)" and bg["groupTypes"] == []
    for ca in g.objs["identity/conditionalAccess/policies"]:
        assert ca["state"] == "enabledForReportingButNotEnforced"
        assert ca["conditions"]["users"]["excludeGroups"] == [bg["id"]]
        assert ca["displayName"].startswith("[HK] ")


def test_moviles_asigna_por_nombre_de_grupo_y_sin_acciones_de_dispositivo(g):
    from app.deploy import deploy
    r = deploy(T, "moviles-v1")
    assert not r["errors"], r["errors"]
    ios_group = next(o for o in g.objs["groups"] if "iOS" in o["displayName"])
    assert ios_group["groupTypes"] == ["DynamicMembership"] and ios_group["membershipRuleProcessingState"] == "On"
    ios_comp = next(o for o in g.objs["deviceManagement/deviceCompliancePolicies"] if "iOS" in o["displayName"])
    target = g.assignments[ios_comp["id"]][0]["assignments"][0]["target"]
    assert target["groupId"] == ios_group["id"]
    actions = {a["actionType"] for o in g.objs["deviceManagement/deviceCompliancePolicies"]
               for rule in o.get("scheduledActionsForRule", []) for a in rule["scheduledActionConfigurations"]}
    assert not actions & {"retire", "wipe", "remoteLock"}
    mam = g.objs["deviceAppManagement/iosManagedAppProtections"][0]
    assert all("id" not in a for a in mam["apps"])
    assert g.assignments[mam["id"]][0]["assignments"][0]["target"]["@odata.type"].endswith("allLicensedUsersAssignmentTarget")


def test_segundo_despliegue_omite_y_modo_update_corrige(g):
    from app.deploy import deploy, plan
    deploy(T, "pyme-windows-v1")
    assert {s["action"] for s in plan(T, "pyme-windows-v1")} == {"skip (ya existe)"}
    assert {s["action"] for s in plan(T, "pyme-windows-v1", "update")} == {"sin cambios"}
    comp = next(o for o in g.objs["deviceManagement/deviceCompliancePolicies"] if o["displayName"].startswith("[HK]"))
    comp["bitLockerEnabled"] = False  # alguien lo cambió a mano
    p = {s["name"]: s for s in plan(T, "pyme-windows-v1", "update")}
    assert p[comp["displayName"]]["changes"] == ["bitLockerEnabled"]
    r = deploy(T, "pyme-windows-v1", "update")
    assert r["updated"][0]["before"]["bitLockerEnabled"] is False
    assert comp["id"] in [u["id"] for u in r["updated"]]
    assert g.get(f"deviceManagement/deviceCompliancePolicies/{comp['id']}")["bitLockerEnabled"] is True


def test_drift_detecta_y_restaura(g):
    from app import drift
    from app.deploy import deploy
    deploy(T, "pyme-windows-v1")
    assert {r["status"] for r in drift.check(T, "pyme-windows-v1")} == {"ok"}
    cfg = g.objs["deviceManagement/deviceConfigurations"][0]
    cfg["cortanaBlocked"] = False
    rows = {r["name"]: r for r in drift.check(T, "pyme-windows-v1")}
    assert rows[cfg["displayName"]]["status"] == "desviado"
    assert rows[cfg["displayName"]]["differences"][0]["property"] == "cortanaBlocked"
    res = drift.restore(T, "pyme-windows-v1")
    assert res["fixed"] and g.objs["deviceManagement/deviceConfigurations"][0]["cortanaBlocked"] is True


def test_rollback_elimina_creados_y_restaura_actualizados(g):
    from app.deploy import deploy, rollback
    r1 = deploy(T, "grupos-y-filtros-v1")
    assert len(r1["created"]) == 20
    r = rollback(T, r1["deployment_id"])
    assert not r["errors"] and len(r["removed"]) == 20
    assert g.objs["groups"] == [] and g.objs["deviceManagement/assignmentFilters"] == []


def test_reset_modo2_solo_quita_lo_del_portal_en_orden_seguro(g):
    from app import reset
    from app.deploy import deploy
    deploy(T, "identidad-segura-v1")
    deploy(T, "pyme-windows-v1")
    prev = reset.preview(T)
    assert all(o["name"].startswith("[HK]") for o in prev)
    assert prev[0]["resource"] == "conditionalAccess" and prev[-1]["resource"] == "groups"
    reset.remove_owned(T)
    assert g.objs["deviceManagement/deviceCompliancePolicies"] == [{"id": "cli-1", "displayName": "Política del cliente"}]
    assert g.objs["identity/conditionalAccess/policies"] == [] and g.objs["groups"] == []


def test_backups_cifrados_en_reposo(g, tmp_path):
    from app import store
    from app.backup import take_backup
    rid = take_backup(T, "prueba")
    raw = (tmp_path / T / "backups" / f"{rid}.json").read_text()
    assert "AES-256-GCM" in raw and "Política del cliente" not in raw
    assert store.load("backups", T, rid)["objects"]["compliance"][0]["displayName"] == "Política del cliente"


def test_referencia_inexistente_se_detecta_en_la_vista_previa(g, tmp_path, monkeypatch):
    import json
    from app import config
    from app.deploy import plan
    b = tmp_path / "bl" / "prueba"
    b.mkdir(parents=True)
    (b / "01.json").write_text(json.dumps({"resource": "compliance", "assign": {"groups": ["No existe"]},
                                           "body": {"@odata.type": "#microsoft.graph.windows10CompliancePolicy", "displayName": "X"}}))
    monkeypatch.setattr(config.settings, "baselines_dir", str(tmp_path / "bl"))
    assert plan(T, "prueba")[0]["action"].startswith("error: falta group: No existe")


def test_api_rutas_basicas(g):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.get("/").status_code == 200
    names = [b["name"] for b in c.get("/baselines").json()]
    assert {"identidad-segura-v1", "moviles-v1", "grupos-y-filtros-v1", "pyme-windows-v1"} <= set(names)
    assert c.post(f"/tenants/{T}/reset/owned", json={"confirm_tenant": "otro"}).status_code == 400
    assert c.get(f"/tenants/{T}/preview/moviles-v1").status_code == 200

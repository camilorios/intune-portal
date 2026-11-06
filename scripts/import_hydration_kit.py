"""Genera baselines del portal a partir de las plantillas MIT de Intune Hydration Kit
(https://github.com/jorgeasaurus/IntuneHydrationKit, (c) 2026 Jorge Suarez, licencia MIT).

No se importan las carpetas OpenIntuneBaseline (GPL-3.0) ni CISBaselines (contenido derivado
de CIS Benchmarks, con licencia propia no comercial). Uso:
    git clone --depth 1 https://github.com/jorgeasaurus/IntuneHydrationKit /tmp/hk
    python scripts/import_hydration_kit.py /tmp/hk
"""
import json
import re
import shutil
import sys
from pathlib import Path

HK = Path(sys.argv[1]) / "Templates"
OUT = Path(__file__).resolve().parent.parent / "baselines"
SOURCE = {"source": "Intune Hydration Kit (MIT) adaptado por JCRsystem",
          "source_url": "https://github.com/jorgeasaurus/IntuneHydrationKit"}
BREAK_GLASS = "Cuentas de emergencia (break-glass)"


def strip_nulls(v):
    if isinstance(v, dict):
        return {k: strip_nulls(x) for k, x in v.items() if x is not None and "@odata.context" not in k}
    if isinstance(v, list):
        return [strip_nulls(x) for x in v]
    return v


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def write(name, meta, items):
    d = OUT / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "_baseline.json").write_text(json.dumps({**meta, **SOURCE}, indent=2, ensure_ascii=False))
    for i, it in enumerate(items, 1):
        n = it["body"].get("displayName") or it["body"].get("name")
        (d / f"{i:02d}-{slug(n)}.json").write_text(json.dumps(it, indent=2, ensure_ascii=False))


def load(p):
    return json.loads((HK / p).read_text(encoding="utf-8-sig"))


def groups(file, names):
    out = []
    for g in load(f"DynamicGroups/{file}")["groups"]:
        if g["displayName"] in names:
            out.append({"resource": "groups", "body": {k: g[k] for k in ("displayName", "description", "membershipRule")}})
    return out


def filters(file):
    return [{"resource": "assignmentFilters", "body": {k: f[k] for k in ("displayName", "description", "platform", "rule")}}
            for f in load(f"Filters/{file}")["filters"]]


# 1) Grupos dinámicos y filtros
grp = groups("OS-Groups.json", {"Intune - Windows Devices", "Intune - Windows 11 Devices", "Intune - macOS Devices",
                                "Intune - iOS iPadOS Devices", "Intune - Android Devices"})
grp += groups("Autopilot-Groups.json", {"Intune - Autopilot Devices"})
grp += groups("Ownership-Groups.json", {"Intune - Corporate Owned Devices", "Intune - BYOD Devices"})
write("grupos-y-filtros-v1", {"title": "Grupos dinámicos y filtros",
      "description": "8 grupos dinámicos por sistema operativo, Autopilot y propiedad, y filtros para máquinas virtuales y Cloud PC. Desplegar antes que las demás baselines."},
      grp + filters("Windows-VM-Filters.json"))

# 2) Identidad segura: acceso condicional en modo solo informe, con grupo de emergencia excluido
ca_names = ["Block legacy authentication", "Require multifactor authentication for admins",
            "Require multifactor authentication for Microsoft admin portals",
            "Require multifactor authentication for Azure management",
            "Require multifactor authentication for all users",
            "Require multifactor authentication for guest access", "Securing security info registration"]
items = [{"resource": "groups", "body": {"displayName": BREAK_GLASS,
          "description": "Cuentas de acceso de emergencia excluidas de todo el acceso condicional. Añade 2 cuentas cloud-only antes de activar las políticas."}}]
for n in ca_names:
    b = strip_nulls(load(f"ConditionalAccess/{n}.json"))
    b.pop("id", None)
    users = b["conditions"].setdefault("users", {})
    users["excludeGroups"] = sorted(set(users.get("excludeGroups", [])) | {f"@group:{BREAK_GLASS}"})
    items.append({"resource": "conditionalAccess", "body": b})
write("identidad-segura-v1", {"title": "Identidad segura (acceso condicional)",
      "description": "MFA para administradores, portales de admin, Azure, todos los usuarios e invitados; bloqueo de autenticación heredada; registro seguro de MFA. Se crea en modo SOLO INFORME y excluye el grupo de emergencia.",
      "requires": "Entra ID P1"}, items)

# 3) Móviles: cumplimiento iOS/Android y protección de apps (MAM) nivel 2
items = groups("OS-Groups.json", {"Intune - iOS iPadOS Devices", "Intune - Android Devices"})
for f, grp_name in [("iOS-Compliance-Basic.json", "Intune - iOS iPadOS Devices"),
                    ("Android-Compliance-FullyManaged-Basic.json", "Intune - Android Devices")]:
    b = strip_nulls(load(f"Compliance/{f}"))
    for rule in b.get("scheduledActionsForRule", []):  # el portal nunca retira ni bloquea dispositivos
        rule["scheduledActionConfigurations"] = [a for a in rule["scheduledActionConfigurations"]
                                                 if a["actionType"] not in ("retire", "wipe", "remoteLock")]
    items.append({"resource": "compliance", "body": b, "assign": {"groups": [grp_name]}})
for f, res in [("level-2-enterprise-enhanced-data-protection-iOS.json", "appProtectionIOS"),
               ("level-2-enterprise-enhanced-data-protection-Android.json", "appProtectionAndroid")]:
    b = strip_nulls(load(f"AppProtection/{f}"))
    b["apps"] = [{k: v for k, v in a.items() if k not in ("id", "version")} for a in b.get("apps", [])]
    for k in ("allowedAndroidDeviceManufacturers", "allowedIosDeviceModels"):
        if b.get(k) == "":
            b.pop(k)
    items.append({"resource": res, "body": b, "assign": {"allUsers": True}})
write("moviles-v1", {"title": "Móviles: cumplimiento y protección de apps",
      "description": "Cumplimiento básico para iOS/iPadOS y Android, y protección de datos empresarial nivel 2 (marco de Microsoft) para las apps de Microsoft 365 en iOS y Android, asignada a todos los usuarios."},
      items)
print("ok")

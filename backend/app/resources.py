"""Catálogo de tipos de objetos que el portal respalda, despliega, compara y restablece.

Inspirado en el catálogo de Micke-K/IntuneManagement (MIT): cada tipo declara su endpoint,
el orden de importación (lo que otros necesitan va primero), las propiedades de solo lectura
que Graph rechaza al crear o actualizar y si admite asignaciones.

- import_order: menor = se crea antes (grupos y filtros antes que las políticas que los usan).
- Para eliminar se usa el orden inverso de dependencias: acceso condicional primero,
  después políticas, y grupos/filtros al final (ver delete_order()).
"""

# Propiedades que nunca se envían al crear (comunes a todos los tipos)
COMMON_READONLY = {
    "id", "createdDateTime", "lastModifiedDateTime", "modifiedDateTime", "version",
    "supportsScopeTags", "deviceManagementApplicabilityRuleOsEdition",
    "deviceManagementApplicabilityRuleOsVersion", "deviceManagementApplicabilityRuleDeviceMode",
    "isAssigned", "settingCount", "creationSource", "assignments",
}

RESOURCES = [
    # --- Identidad y destino de asignaciones (se crean primero) ---
    {"key": "groups", "title": "Grupos", "path": "groups", "version": "v1.0", "import_order": 10,
     "remove": {"renewedDateTime", "securityIdentifier", "onPremisesProvisioningErrors", "proxyAddresses",
                "deletedDateTime", "mail", "membershipRuleProcessingStatus"},
     "list_filter": "$select=id,displayName,description,groupTypes,membershipRule,membershipRuleProcessingState,securityEnabled,mailEnabled,mailNickname"},
    {"key": "assignmentFilters", "title": "Filtros de asignación", "path": "deviceManagement/assignmentFilters",
     "version": "beta", "import_order": 20, "remove": {"payloads"}},
    # --- Políticas de Intune ---
    {"key": "compliance", "title": "Cumplimiento", "path": "deviceManagement/deviceCompliancePolicies",
     "version": "v1.0", "import_order": 40, "assign": True,
     "remove_update": {"scheduledActionsForRule"}},
    {"key": "deviceConfigurations", "title": "Perfiles de configuración", "path": "deviceManagement/deviceConfigurations",
     "version": "beta", "import_order": 40, "assign": True, "remove": {"privacyAccessControls"}},
    {"key": "settingsCatalog", "title": "Settings Catalog", "path": "deviceManagement/configurationPolicies",
     "version": "beta", "import_order": 40, "assign": True, "name_field": "name",
     "expand": "settings", "no_patch": True},  # Graph no permite PATCH de settings: se recrea
    {"key": "adminTemplates", "title": "Plantillas administrativas", "path": "deviceManagement/groupPolicyConfigurations",
     "version": "beta", "import_order": 40, "assign": True, "remove": {"definitionValues", "policyConfigurationIngestionType"}},
    {"key": "endpointSecurity", "title": "Endpoint Security (intents)", "path": "deviceManagement/intents",
     "version": "beta", "import_order": 40, "assign": True, "remove": {"settings"}, "readonly_deploy": True},
    {"key": "powershellScripts", "title": "Scripts PowerShell", "path": "deviceManagement/deviceManagementScripts",
     "version": "beta", "import_order": 40, "assign": True},
    {"key": "remediations", "title": "Remediaciones", "path": "deviceManagement/deviceHealthScripts",
     "version": "beta", "import_order": 40, "assign": True, "remove": {"highestAvailableVersion", "isGlobalScript"}},
    {"key": "featureUpdates", "title": "Feature updates", "path": "deviceManagement/windowsFeatureUpdateProfiles",
     "version": "beta", "import_order": 40, "assign": True, "remove": {"deployableContentDisplayName", "endOfSupportDate"}},
    {"key": "driverUpdates", "title": "Driver updates", "path": "deviceManagement/windowsDriverUpdateProfiles",
     "version": "beta", "import_order": 40, "assign": True, "remove": {"inventorySyncStatus", "newUpdates", "deviceReporting"}},
    {"key": "autopilotProfiles", "title": "Perfiles de Autopilot", "path": "deviceManagement/windowsAutopilotDeploymentProfiles",
     "version": "beta", "import_order": 50, "assign": True, "remove_update": {"managementServiceAppId"}},
    {"key": "enrollmentConfigurations", "title": "Inscripción (ESP y restricciones)", "path": "deviceManagement/deviceEnrollmentConfigurations",
     "version": "beta", "import_order": 50, "assign": True, "remove_update": {"priority"}},
    {"key": "mobileApps", "title": "Aplicaciones", "path": "deviceAppManagement/mobileApps", "version": "beta",
     "import_order": 60, "assign": True, "readonly_deploy": True,  # paquetes binarios: solo backup por ahora
     "remove": {"uploadState", "publishingState", "dependentAppCount", "supersedingAppCount",
                "supersededAppCount", "committedContentVersion", "isFeatured", "size", "categories"}},
    {"key": "appProtectionIOS", "title": "Protección de apps iOS", "path": "deviceAppManagement/iosManagedAppProtections",
     "version": "beta", "import_order": 70, "assign": True, "assign_users": True,
     "remove": {"deployedAppCount", "exemptAppLockerFiles", "targetedAppManagementLevels"}},
    {"key": "appProtectionAndroid", "title": "Protección de apps Android", "path": "deviceAppManagement/androidManagedAppProtections",
     "version": "beta", "import_order": 70, "assign": True, "assign_users": True,
     "remove": {"deployedAppCount", "targetedAppManagementLevels"}},
    # --- Acceso condicional (se crea en modo solo informe, se elimina primero) ---
    {"key": "conditionalAccess", "title": "Acceso condicional", "path": "identity/conditionalAccess/policies",
     "version": "beta", "import_order": 90, "remove": {"templateId", "partialEnablementStrategy"}},
    {"key": "namedLocations", "title": "Ubicaciones con nombre", "path": "identity/conditionalAccess/namedLocations",
     "version": "v1.0", "import_order": 30},
]

BY_KEY = {r["key"]: r for r in RESOURCES}

# Tipos antiguos de baselines anteriores (compatibilidad)
ALIASES = {"appProtection": "appProtectionIOS"}


def get(key: str) -> dict:
    return BY_KEY[ALIASES.get(key, key)]


def name_of(resource: dict, obj: dict) -> str:
    return obj.get(resource.get("name_field", "displayName")) or ""


def delete_order() -> list[dict]:
    """Orden seguro para eliminar: acceso condicional → políticas → apps → filtros → grupos."""
    return sorted(RESOURCES, key=lambda r: -r["import_order"])


def clean_body(resource: dict, body: dict, for_update: bool = False) -> dict:
    """Quita propiedades de solo lectura, anotaciones OData de contexto y nulos innecesarios."""
    drop = COMMON_READONLY | resource.get("remove", set())
    if for_update:
        drop |= resource.get("remove_update", set())
    out = {}
    for k, v in body.items():
        if k in drop:
            continue
        if "@odata." in k and k != "@odata.type":  # p.ej. authenticationStrength@odata.context
            continue
        out[k] = _strip_odata_context(v)
    return out


def _strip_odata_context(v):
    if isinstance(v, dict):
        return {k: _strip_odata_context(x) for k, x in v.items() if not ("@odata." in k and k != "@odata.type")}
    if isinstance(v, list):
        return [_strip_odata_context(x) for x in v]
    return v

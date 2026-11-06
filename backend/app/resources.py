"""Tipos de objetos de Intune que el portal respalda, despliega y restablece.
El orden importa para el reset: lo primero de la lista se elimina primero."""

RESOURCES = [
    {"key": "conditionalAccess", "path": "identity/conditionalAccess/policies", "version": "v1.0"},
    {"key": "compliance", "path": "deviceManagement/deviceCompliancePolicies", "version": "v1.0", "assign": True},
    {"key": "deviceConfigurations", "path": "deviceManagement/deviceConfigurations", "version": "v1.0", "assign": True},
    {"key": "settingsCatalog", "path": "deviceManagement/configurationPolicies", "version": "beta", "assign": True, "name_field": "name"},
    {"key": "autopilotProfiles", "path": "deviceManagement/windowsAutopilotDeploymentProfiles", "version": "beta"},
    {"key": "appProtection", "path": "deviceAppManagement/managedAppPolicies", "version": "v1.0"},
    {"key": "enrollmentConfigurations", "path": "deviceManagement/deviceEnrollmentConfigurations", "version": "v1.0"},
    {"key": "mobileApps", "path": "deviceAppManagement/mobileApps", "version": "v1.0"},
]

BY_KEY = {r["key"]: r for r in RESOURCES}


def name_of(resource: dict, obj: dict) -> str:
    return obj.get(resource.get("name_field", "displayName"), "")

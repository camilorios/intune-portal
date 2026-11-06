from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    client_id: str
    client_secret: str  # en producción: certificado en Azure Key Vault
    redirect_uri: str = "http://localhost:8000/onboarding/callback"
    object_prefix: str = "[HK]"
    data_dir: str = "./data"
    baselines_dir: str = "./baselines"
    # Clave AES-256 en base64 (32 bytes) para cifrar backups y snapshots en reposo.
    # Generar con: python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
    backup_key: str = ""
    # Estado con el que se crea el acceso condicional: solo informe hasta que el técnico lo active
    ca_state: str = "enabledForReportingButNotEnforced"


settings = Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    client_id: str
    client_secret: str  # en producción: certificado en Azure Key Vault
    redirect_uri: str = "http://localhost:8000/onboarding/callback"
    object_prefix: str = "[HK]"
    data_dir: str = "./data"
    baselines_dir: str = "./baselines"


settings = Settings()

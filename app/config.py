from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Gmail (IMAP)
    gmail_user_email: str = ""
    gmail_app_password: str = ""
    gmail_poll_interval_seconds: int = 60

    # Anthropic
    anthropic_api_key: str = ""

    # Xero
    xero_client_id: str = ""
    xero_client_secret: str = ""
    xero_redirect_uri: str = ""
    xero_default_account_code: str = "400"

    # App
    app_base_url: str = "http://localhost:8000"
    database_path: str = "data/app.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

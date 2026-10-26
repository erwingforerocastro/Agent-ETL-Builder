"""Application composition root."""

from infrastructure.config.settings import Settings
from interfaces.api.app import create_app

settings = Settings.from_env()
app = create_app(service_name=settings.service_name, version=settings.version)

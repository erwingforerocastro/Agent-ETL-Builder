"""Application composition root."""

from infrastructure.config.settings import Settings
from infrastructure.registry.module_registry import build_module_registry
from infrastructure.state.checkpointing import create_in_memory_checkpointer
from interfaces.api.app import create_app

settings = Settings.from_env()
checkpointer = create_in_memory_checkpointer()
module_registry = build_module_registry()
app = create_app(service_name=settings.service_name, version=settings.version)
app.state.checkpointer = checkpointer
app.state.module_registry = module_registry

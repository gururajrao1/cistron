"""VoidSignal FastAPI REST gateway."""

from voidsignal.api.app import app, create_app, resolve_preset

__all__ = ["app", "create_app", "resolve_preset"]

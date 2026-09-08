from .client import router as client_router
from .admin import router as admin_router

__all__ = ["client_router", "admin_router"]

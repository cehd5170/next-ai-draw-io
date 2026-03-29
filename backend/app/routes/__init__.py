"""
Routes package — registers all APIRouter instances.

Usage in ``app/main.py``::

    from app.routes import all_routers

    for router in all_routers:
        app.include_router(router, prefix="/api")

Or import individual routers::

    from app.routes.chat import router as chat_router
"""

from app.routes.chat import router as chat_router
from app.routes.chat_agents import router as chat_agents_router
from app.routes.config import router as config_router
from app.routes.export_pptx import router as export_pptx_router
from app.routes.log_feedback import router as log_feedback_router
from app.routes.log_save import router as log_save_router
from app.routes.parse_url import router as parse_url_router
from app.routes.server_models import router as server_models_router
from app.routes.validate_diagram import router as validate_diagram_router
from app.routes.validate_model import router as validate_model_router
from app.routes.verify_access import router as verify_access_router

__all__ = [
    "chat_router",
    "chat_agents_router",
    "config_router",
    "export_pptx_router",
    "log_feedback_router",
    "log_save_router",
    "parse_url_router",
    "server_models_router",
    "validate_diagram_router",
    "validate_model_router",
    "verify_access_router",
    "all_routers",
]

# Convenience list for bulk registration in main.py
all_routers = [
    chat_router,
    chat_agents_router,
    config_router,
    server_models_router,
    verify_access_router,
    validate_model_router,
    validate_diagram_router,
    log_feedback_router,
    log_save_router,
    parse_url_router,
    export_pptx_router,
]

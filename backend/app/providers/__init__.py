"""
AI provider factory package.

Public surface::

    from app.providers import (
        get_ai_model,
        get_validation_model,
        supports_image_input,
        supports_prompt_caching,
    )
"""

from app.providers.factory import (
    get_ai_model,
    get_validation_model,
    supports_image_input,
    supports_prompt_caching,
)

__all__ = [
    "get_ai_model",
    "get_validation_model",
    "supports_image_input",
    "supports_prompt_caching",
]

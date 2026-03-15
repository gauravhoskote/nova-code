"""Nova Code core — framework-agnostic public API.

Import from here to use Nova Code without any CLI dependency::

    from novacode.core import ChatSession, TurnCallbacks
"""

from .session import ChatSession, TurnCallbacks, DEFAULT_SYSTEM_PROMPT

__all__ = ["ChatSession", "TurnCallbacks", "DEFAULT_SYSTEM_PROMPT"]

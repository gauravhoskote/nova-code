"""Nova Code core — framework-agnostic public API.

Import from here to use Nova Code without any CLI dependency::

    from novacode.core import ChatSession, TurnCallbacks, run_ask
"""

from .session import ChatSession, TurnCallbacks, DEFAULT_SYSTEM_PROMPT
from .ask import run_ask

__all__ = ["ChatSession", "TurnCallbacks", "DEFAULT_SYSTEM_PROMPT", "run_ask"]

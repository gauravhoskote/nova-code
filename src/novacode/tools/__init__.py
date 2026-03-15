"""
Nova Code tool registry.

Built-in tools are auto-registered by importing their modules below.

To add a custom tool:
    1. Create src/novacode/tools/my_tool.py
    2. Define a function with the @tool decorator
    3. Call register(my_function) at the bottom of the file
    4. Add `from . import my_tool` in this file

Example tool file:
    from langchain_core.tools import tool
    from . import register

    @tool
    def my_tool(arg: str) -> str:
        \"\"\"Description the LLM sees when deciding to use this tool.\"\"\"
        return f"result: {arg}"

    register(my_tool)
"""

from typing import List
from langchain_core.tools import BaseTool

_registry: List[BaseTool] = []

# Tools that only read data — executed automatically without user approval.
READ_ONLY_TOOLS = frozenset({
    "read_file",
    "glob_files",
    "grep",
    "list_directory",
    "web_search",
    "web_fetch",
    "todo_read",
    "notebook_read",
})


def register(*tools: BaseTool) -> None:
    """Register one or more tools with the Nova Code tool registry."""
    _registry.extend(tools)


def all_tools() -> List[BaseTool]:
    """Return all registered tools."""
    return list(_registry)


# ── Built-in tools (each module calls register() on import) ────────────────
from . import bash           # noqa: E402, F401
from . import edit           # noqa: E402, F401
from . import multi_edit     # noqa: E402, F401
from . import glob_tool      # noqa: E402, F401
from . import grep           # noqa: E402, F401
from . import ls             # noqa: E402, F401
from . import read           # noqa: E402, F401
from . import write          # noqa: E402, F401
from . import web_search     # noqa: E402, F401
from . import web_fetch      # noqa: E402, F401
from . import todo_read      # noqa: E402, F401
from . import todo_write     # noqa: E402, F401
from . import notebook_read  # noqa: E402, F401
from . import notebook_edit  # noqa: E402, F401

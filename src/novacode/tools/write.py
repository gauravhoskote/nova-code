import os
from langchain_core.tools import tool
from . import register


@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file, creating parent directories if needed.

    Args:
        path: Absolute or relative path to the file.
        content: Full content to write (overwrites existing content).

    Returns a success message or an error description.
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        lines = content.count("\n") + 1
        return f"Written {len(content)} chars ({lines} lines) to {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


register(write_file)

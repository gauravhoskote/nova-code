from typing import Optional

from langchain_core.tools import tool
from . import register

MAX_CHARS = 20_000  # truncate very large files


@tool
def read_file(path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """Read the contents of a file.

    Args:
        path: Absolute or relative path to the file.
        start_line: First line to read (1-indexed, optional).
        end_line: Last line to read (1-indexed, inclusive, optional).

    Returns the file contents as a string, with line numbers prefixed.
    """
    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()

        if start_line is not None or end_line is not None:
            s = (start_line or 1) - 1
            e = end_line or len(lines)
            lines = lines[s:e]
            offset = s
        else:
            offset = 0

        numbered = "".join(f"{offset + i + 1:>6}  {line}" for i, line in enumerate(lines))

        if len(numbered) > MAX_CHARS:
            numbered = numbered[:MAX_CHARS] + f"\n... [truncated — {len(lines)} lines total]"

        return numbered or "(empty file)"
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"


register(read_file)

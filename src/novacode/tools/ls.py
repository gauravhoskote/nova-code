import os
from langchain_core.tools import tool
from . import register


@tool
def list_directory(path: str = ".") -> str:
    """List the files and subdirectories at the given path.

    Args:
        path: Directory to list (default: current working directory).

    Returns a sorted listing showing type (file/dir), size, and name.
    Hidden files (starting with .) are included.
    """
    try:
        abs_path = os.path.abspath(path)
        if not os.path.exists(abs_path):
            return f"Error: path not found: {path}"
        if not os.path.isdir(abs_path):
            return f"Error: not a directory: {path}"

        entries = os.listdir(abs_path)
        entries.sort(key=lambda e: (not os.path.isdir(os.path.join(abs_path, e)), e.lower()))

        lines = [f"Contents of {abs_path}:"]
        for entry in entries:
            full = os.path.join(abs_path, entry)
            if os.path.isdir(full):
                lines.append(f"  DIR   {entry}/")
            else:
                try:
                    size = os.path.getsize(full)
                    size_str = _human_size(size)
                except OSError:
                    size_str = "?"
                lines.append(f"  {size_str:>7}  {entry}")

        lines.append(f"\n{len(entries)} items")
        return "\n".join(lines)
    except PermissionError:
        return f"Error: permission denied: {path}"
    except Exception as e:
        return f"Error: {e}"


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


register(list_directory)

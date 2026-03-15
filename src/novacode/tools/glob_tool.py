import glob as _glob
import os
from langchain_core.tools import tool
from . import register

MAX_RESULTS = 200


@tool
def glob_files(pattern: str, directory: str = ".") -> str:
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern such as '**/*.py', 'src/*.ts', or '*.json'.
                 Use ** for recursive matching.
        directory: Root directory to search from (default: current directory).

    Returns a newline-separated list of matching file paths, sorted by
    modification time (newest first), or a message if nothing matched.
    """
    try:
        base = os.path.abspath(directory)
        full_pattern = os.path.join(base, pattern)
        matches = _glob.glob(full_pattern, recursive=True)

        if not matches:
            return f"No files matched: {pattern} in {directory}"

        def _mtime(p: str) -> float:
            try:
                return os.path.getmtime(p)
            except OSError:
                return 0.0

        matches.sort(key=_mtime, reverse=True)

        if len(matches) > MAX_RESULTS:
            truncated = matches[:MAX_RESULTS]
            suffix = f"\n... and {len(matches) - MAX_RESULTS} more"
        else:
            truncated = matches
            suffix = ""

        # Show relative paths for readability
        rel = [os.path.relpath(p, base) for p in truncated]
        return "\n".join(rel) + suffix
    except Exception as e:
        return f"Error: {e}"


register(glob_files)

import os
import re
from langchain_core.tools import tool
from . import register

MAX_MATCHES = 100
BINARY_CHECK_SIZE = 8_000


def _is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(BINARY_CHECK_SIZE)
    except Exception:
        return True


@tool
def grep(
    pattern: str,
    path: str = ".",
    include: str = None,
    case_sensitive: bool = True,
) -> str:
    """Search for a regex pattern in files, like ripgrep/grep.

    Args:
        pattern: Regular expression to search for.
        path: File or directory to search (default: current directory).
              Searches recursively when a directory is given.
        include: Glob pattern to filter filenames, e.g. '*.py' or '*.{ts,tsx}'.
        case_sensitive: Whether the match is case-sensitive (default True).

    Returns matching lines in the format  file:line_number:content,
    or a summary if no matches are found.
    """
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Invalid regex: {e}"

    include_re = None
    if include:
        # Convert glob-style include to a regex.
        # Step 1: expand brace alternation, e.g. {ts,tsx} → (ts|tsx)
        inc_pattern = re.sub(
            r"\{([^}]+)\}",
            lambda m: "(" + "|".join(re.escape(p) for p in m.group(1).split(",")) + ")",
            include,
        )
        # Step 2: translate remaining glob wildcards (* and ?)
        inc_pattern = (
            inc_pattern
            .replace(".", r"\.")
            .replace("*", ".*")
            .replace("?", ".")
        )
        include_re = re.compile(inc_pattern + "$")

    matches = []
    abs_path = os.path.abspath(path)

    def search_file(filepath: str):
        if include_re and not include_re.search(os.path.basename(filepath)):
            return
        if _is_binary(filepath):
            return
        try:
            with open(filepath, "r", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    if regex.search(line):
                        rel = os.path.relpath(filepath, ".")
                        matches.append(f"{rel}:{lineno}:{line.rstrip()}")
                        if len(matches) >= MAX_MATCHES:
                            return
        except Exception:
            pass

    if os.path.isfile(abs_path):
        search_file(abs_path)
    elif os.path.isdir(abs_path):
        for root, dirs, files in os.walk(abs_path):
            # Skip hidden and common noise directories
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git")]
            for fname in files:
                search_file(os.path.join(root, fname))
                if len(matches) >= MAX_MATCHES:
                    break
            if len(matches) >= MAX_MATCHES:
                break
    else:
        return f"Error: path not found: {path}"

    if not matches:
        return f"No matches for '{pattern}' in {path}"

    result = "\n".join(matches)
    if len(matches) >= MAX_MATCHES:
        result += f"\n... [stopped at {MAX_MATCHES} matches]"
    return result


register(grep)

from langchain_core.tools import tool
from . import register


@tool
def edit_file(path: str, old_string: str, new_string: str) -> str:
    """Replace an exact string in a file with a new string.

    The old_string must appear exactly once in the file to avoid
    ambiguous edits. Use read_file first to confirm the exact text.

    Args:
        path: Path to the file to edit.
        old_string: The exact text to find and replace.
        new_string: The text to replace it with.

    Returns a success message or an error description.
    """
    try:
        with open(path, "r", errors="replace") as f:
            content = f.read()

        count = content.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {path}"
        if count > 1:
            return (
                f"Error: old_string appears {count} times in {path}. "
                "Provide more surrounding context to make it unique."
            )

        new_content = content.replace(old_string, new_string, 1)
        with open(path, "w") as f:
            f.write(new_content)

        return f"Edited {path}: replaced 1 occurrence."
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as e:
        return f"Error editing {path}: {e}"


register(edit_file)

import json
from langchain_core.tools import tool
from . import register


@tool
def multi_edit(path: str, edits: str) -> str:
    """Perform multiple find-and-replace operations in a file atomically.

    All edits are validated before any are applied. If any edit's old_string
    is not found or appears more than once, the entire operation is aborted
    with no changes made.

    Args:
        path: Path to the file to edit.
        edits: JSON array of edit objects, each with "old_string" and
               "new_string" keys. Example:
               '[{"old_string": "foo", "new_string": "bar"},
                 {"old_string": "baz", "new_string": "qux"}]'

    Returns a success summary or an error description.
    """
    try:
        edit_list = json.loads(edits)
    except json.JSONDecodeError as e:
        return f"Error: edits must be a valid JSON array: {e}"

    if not isinstance(edit_list, list) or not edit_list:
        return "Error: edits must be a non-empty JSON array of {old_string, new_string} objects."

    for i, item in enumerate(edit_list):
        if not isinstance(item, dict) or "old_string" not in item or "new_string" not in item:
            return f"Error: edit[{i}] must have 'old_string' and 'new_string' keys."

    try:
        with open(path, "r", errors="replace") as f:
            content = f.read()
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"

    # Validate and apply edits against the progressively modified content so
    # that uniqueness checks reflect the actual state at each edit's turn.
    # This prevents an earlier edit from silently introducing new occurrences
    # that break the uniqueness guarantee for a later edit.
    for i, item in enumerate(edit_list):
        old = item["old_string"]
        count = content.count(old)
        if count == 0:
            return f"Error: edit[{i}] old_string not found in {path}. No changes made."
        if count > 1:
            return (
                f"Error: edit[{i}] old_string appears {count} times in {path}. "
                "Provide more surrounding context to make it unique. No changes made."
            )
        content = content.replace(old, item["new_string"], 1)

    try:
        with open(path, "w") as f:
            f.write(content)
    except Exception as e:
        return f"Error writing {path}: {e}"

    return f"Edited {path}: applied {len(edit_list)} replacement(s) successfully."


register(multi_edit)

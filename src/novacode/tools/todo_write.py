import json
import os
from langchain_core.tools import tool
from . import register

_TODO_FILE = os.path.expanduser("~/.novacode_todos.json")
_VALID_STATUSES = {"pending", "in_progress", "completed"}


@tool
def todo_write(todos: str) -> str:
    """Create or replace the to-do list with a new set of todos.

    Replaces the entire todo list. To update a single item, pass the full
    list with the updated item included.

    Args:
        todos: JSON array of todo objects. Each object must have:
               - "content" (str): Description of the task.
               - "status"  (str): One of 'pending', 'in_progress', or 'completed'.
               Example:
               '[{"content": "Write tests", "status": "in_progress"},
                 {"content": "Update docs", "status": "pending"}]'

    Returns a confirmation message or an error description.
    """
    try:
        todo_list = json.loads(todos)
    except json.JSONDecodeError as e:
        return f"Error: todos must be a valid JSON array: {e}"

    if not isinstance(todo_list, list):
        return "Error: todos must be a JSON array."

    for i, item in enumerate(todo_list):
        if not isinstance(item, dict):
            return f"Error: todo[{i}] must be an object with 'content' and 'status'."
        if "content" not in item:
            return f"Error: todo[{i}] is missing required field 'content'."
        status = item.get("status", "pending")
        if status not in _VALID_STATUSES:
            return (
                f"Error: todo[{i}] has invalid status '{status}'. "
                f"Must be one of: {', '.join(sorted(_VALID_STATUSES))}."
            )

    try:
        with open(_TODO_FILE, "w") as f:
            json.dump(todo_list, f, indent=2)
    except Exception as e:
        return f"Error saving todos: {e}"

    counts = {s: sum(1 for t in todo_list if t.get("status") == s) for s in _VALID_STATUSES}
    return (
        f"Todo list updated: {len(todo_list)} item(s) — "
        f"{counts['completed']} completed, {counts['in_progress']} in progress, "
        f"{counts['pending']} pending."
    )


register(todo_write)

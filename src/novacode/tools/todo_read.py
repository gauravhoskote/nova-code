import json
import os
from langchain_core.tools import tool
from . import register

_TODO_FILE = os.path.expanduser("~/.novacode_todos.json")


@tool
def todo_read() -> str:
    """Read the current to-do list for this session.

    Returns a formatted list of all current todos with their statuses,
    or a message if no todos exist.

    Todo items have:
        - content: Description of the task
        - status:  'pending', 'in_progress', or 'completed'
    """
    if not os.path.exists(_TODO_FILE):
        return "No todos found. Use todo_write to create a todo list."

    try:
        with open(_TODO_FILE, "r") as f:
            todos = json.load(f)
    except Exception as e:
        return f"Error reading todos: {e}"

    if not todos:
        return "Todo list is empty."

    status_icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    lines = [f"Todo list ({len(todos)} items):"]
    for i, item in enumerate(todos, 1):
        status = item.get("status", "pending")
        icon = status_icon.get(status, "[ ]")
        content = item.get("content", "(no description)")
        lines.append(f"  {i}. {icon} {content}")

    return "\n".join(lines)


register(todo_read)

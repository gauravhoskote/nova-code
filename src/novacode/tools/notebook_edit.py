import json
import os
from langchain_core.tools import tool
from . import register

_VALID_MODES = {"replace", "insert", "delete"}
_VALID_CELL_TYPES = {"code", "markdown"}


@tool
def notebook_edit(
    path: str,
    cell_number: int,
    new_source: str = "",
    cell_type: str = "code",
    edit_mode: str = "replace",
) -> str:
    """Edit a cell in a Jupyter notebook (.ipynb file).

    Supports three edit modes:
      - replace: Replace the source of an existing cell (default).
      - insert:  Insert a new cell before the given cell_number index.
      - delete:  Delete the cell at the given cell_number index.

    Args:
        path:        Path to the .ipynb notebook file.
        cell_number: 0-indexed cell position.
        new_source:  New source text for the cell (used in replace/insert).
        cell_type:   Cell type for inserted cells: 'code' or 'markdown'.
        edit_mode:   One of 'replace', 'insert', or 'delete'.

    Returns a success message or an error description. Clears execution
    count and outputs when a code cell's source is modified.
    """
    if edit_mode not in _VALID_MODES:
        return f"Error: edit_mode must be one of: {', '.join(sorted(_VALID_MODES))}."
    if edit_mode == "insert" and cell_type not in _VALID_CELL_TYPES:
        return f"Error: cell_type must be one of: {', '.join(sorted(_VALID_CELL_TYPES))}."

    try:
        with open(path, "r", errors="replace") as f:
            nb = json.load(f)
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except json.JSONDecodeError as e:
        return f"Error: not a valid notebook (JSON parse error): {e}"
    except Exception as e:
        return f"Error reading {path}: {e}"

    cells = nb.get("cells", [])
    n = len(cells)

    if edit_mode == "replace":
        if cell_number < 0 or cell_number >= n:
            return f"Error: cell_number {cell_number} is out of range (notebook has {n} cell(s), 0-indexed)."
        cell = cells[cell_number]
        cell["source"] = new_source
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
        action = f"Replaced cell [{cell_number}]"

    elif edit_mode == "insert":
        if cell_number < 0 or cell_number > n:
            return f"Error: cell_number {cell_number} is out of range for insert (valid: 0–{n})."
        if cell_type == "code":
            new_cell = {
                "cell_type": "code",
                "source": new_source,
                "metadata": {},
                "outputs": [],
                "execution_count": None,
            }
        else:
            new_cell = {
                "cell_type": "markdown",
                "source": new_source,
                "metadata": {},
            }
        cells.insert(cell_number, new_cell)
        action = f"Inserted {cell_type} cell at [{cell_number}]"

    elif edit_mode == "delete":
        if cell_number < 0 or cell_number >= n:
            return f"Error: cell_number {cell_number} is out of range (notebook has {n} cell(s), 0-indexed)."
        cells.pop(cell_number)
        action = f"Deleted cell [{cell_number}]"

    nb["cells"] = cells

    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(nb, f, indent=1)
        os.replace(tmp, path)
    except Exception as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return f"Error writing {path}: {e}"

    return f"{action} in {path} (notebook now has {len(cells)} cell(s))."


register(notebook_edit)

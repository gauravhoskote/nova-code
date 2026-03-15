import json
from langchain_core.tools import tool
from . import register

MAX_CHARS = 30_000


@tool
def notebook_read(path: str) -> str:
    """Read and display all cells of a Jupyter notebook (.ipynb file).

    Returns each cell's type (code/markdown), source content, and any
    text outputs from the most recent execution.

    Args:
        path: Absolute or relative path to the .ipynb notebook file.

    Returns a formatted representation of all cells and their outputs.
    """
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
    if not cells:
        return f"Notebook {path} has no cells."

    lines = [f"Notebook: {path}  ({len(cells)} cells)\n{'─' * 60}"]

    for idx, cell in enumerate(cells):
        cell_type = cell.get("cell_type", "unknown")
        source = cell.get("source", [])
        if isinstance(source, list):
            source = "".join(source)

        lines.append(f"\n[{idx}] {cell_type.upper()}")
        lines.append(source if source.strip() else "(empty)")

        # Show text outputs for code cells
        outputs = cell.get("outputs", [])
        text_outputs = []
        for out in outputs:
            out_type = out.get("output_type", "")
            if out_type in ("stream", "display_data", "execute_result"):
                text = out.get("text") or out.get("data", {}).get("text/plain", [])
                if isinstance(text, list):
                    text = "".join(text)
                if text.strip():
                    text_outputs.append(text.rstrip())
            elif out_type == "error":
                ename = out.get("ename", "Error")
                evalue = out.get("evalue", "")
                text_outputs.append(f"{ename}: {evalue}")

        if text_outputs:
            lines.append("── Output:")
            lines.append("\n".join(text_outputs))

    result = "\n".join(lines)
    if len(result) > MAX_CHARS:
        result = result[:MAX_CHARS] + f"\n... [truncated — {len(result)} chars total]"

    return result


register(notebook_read)

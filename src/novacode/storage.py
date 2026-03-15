"""
Session persistence for Nova Code.

Directory layout:

    ~/.novacode/
    └── projects/
        └── -Users-you-myproject/      # cwd with / replaced by -
            ├── 20260223T103000.json
            ├── 20260223T154500.json
            └── ...

Each JSON file is one chat session:
    {
        "model":      "global.amazon.nova-2-lite-v1:0",
        "cwd":        "/Users/you/myproject",
        "created_at": "2026-02-23T10:30:00",
        "updated_at": "2026-02-23T10:45:00",
        "messages": [
            {"role": "user",      "content": "..."},
            {"role": "assistant", "content": "..."},
            ...
        ]
    }
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

NOVA_HOME = Path.home() / ".novacode"
PROJECTS_DIR = NOVA_HOME / "projects"
_NOVA_MD = "NOVA.md"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _project_key(cwd: Optional[str] = None) -> str:
    """Convert an absolute path to a filesystem-safe directory name.

    Replaces path separators with '-'.
    e.g. /Users/you/myproject  →  -Users-you-myproject
    """
    path = os.path.abspath(cwd or os.getcwd())
    return path.replace("/", "-").replace("\\", "-")


def project_dir(cwd: Optional[str] = None) -> Path:
    return PROJECTS_DIR / _project_key(cwd)


def slugify(text: str, max_len: int = 100) -> str:
    """Convert free text to a filesystem-safe slug.

    Keeps alphanumerics, replaces whitespace runs with a single hyphen,
    strips everything else, and trims to *max_len* characters.
    """
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'\s+', '-', text.strip())
    text = re.sub(r'-+', '-', text)
    return text[:max_len].strip('-')


# ---------------------------------------------------------------------------
# NOVA.md — persistent project instructions (mirrors Claude Code's CLAUDE.md)
#
# Lookup order (both loaded and concatenated when present):
#   1. ~/.novacode/NOVA.md   — global instructions, applied to every project
#   2. <cwd>/NOVA.md          — project-specific instructions
# ---------------------------------------------------------------------------

def load_nova_md(cwd: Optional[str] = None) -> Tuple[str, List[Path]]:
    """Read global and project-level NOVA.md files.

    Returns (combined_content, list_of_loaded_paths).
    combined_content is an empty string when no files are found.
    """
    parts: List[str] = []
    sources: List[Path] = []

    candidates = [
        NOVA_HOME / _NOVA_MD,
        Path(os.path.abspath(cwd or os.getcwd())) / _NOVA_MD,
    ]

    for path in candidates:
        if path.is_file():
            try:
                text = path.read_text(errors="replace").strip()
                if text:
                    parts.append(text)
                    sources.append(path)
            except Exception:
                pass

    return "\n\n".join(parts), sources


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _messages_to_json(messages: List[BaseMessage]) -> List[dict]:
    out = []
    for m in messages:
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            out.append({"role": "assistant", "content": m.content})
    return out


def _messages_from_json(data: List[dict]) -> List[BaseMessage]:
    result = []
    for item in data:
        if item["role"] == "user":
            result.append(HumanMessage(content=item["content"]))
        elif item["role"] == "assistant":
            result.append(AIMessage(content=item["content"]))
    return result


# ---------------------------------------------------------------------------
# Session file operations
# ---------------------------------------------------------------------------

def new_session_file(cwd: Optional[str] = None) -> Path:
    """Return a path for a brand-new session file (not yet written to disk)."""
    pdir = project_dir(cwd)
    pdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    return pdir / f"{ts}.json"


def latest_session_file(cwd: Optional[str] = None) -> Optional[Path]:
    """Return the most recently modified session file, or None."""
    pdir = project_dir(cwd)
    if not pdir.exists():
        return None
    files = sorted(pdir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def list_session_files(cwd: Optional[str] = None) -> List[Path]:
    """Return all session files, newest first."""
    pdir = project_dir(cwd)
    if not pdir.exists():
        return []
    return sorted(pdir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def list_sessions_info(cwd: Optional[str] = None) -> List[dict]:
    """Return display metadata for all sessions, newest first.

    Each entry: ``{"path": str, "title": str, "created_at": str}``

    *title* is the first 100 characters of the first user message, falling
    back to the filename stem when the file cannot be read.
    """
    result = []
    for path in list_session_files(cwd):
        try:
            with open(path) as f:
                data = json.load(f)
            msgs = data.get("messages", [])
            first_user = next(
                (m["content"][:100] for m in msgs if m.get("role") == "user"),
                "",
            )
            result.append({
                "path": str(path),
                "title": first_user or path.stem,
                "created_at": data.get("created_at", ""),
            })
        except Exception:
            result.append({"path": str(path), "title": path.stem, "created_at": ""})
    return result


def save_session(session_file: Path, messages: List[BaseMessage], model_id: str,
                 created_at: Optional[str] = None):
    """Write (or overwrite) a session file atomically.

    Writes to a sibling .tmp file first, then renames it over the target so a
    crash mid-write never leaves a truncated/corrupt JSON file behind.
    """
    session_file.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()
    payload = {
        "model":      model_id,
        "cwd":        os.getcwd(),
        "created_at": created_at or now,
        "updated_at": now,
        "messages":   _messages_to_json(messages),
    }
    tmp_file = session_file.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_file, session_file)


def load_session(session_file: Path) -> Tuple[List[BaseMessage], str, str]:
    """Load a session file.  Returns (messages, model_id, created_at)."""
    with open(session_file) as f:
        data = json.load(f)
    messages   = _messages_from_json(data.get("messages", []))
    model_id   = data.get("model", "")
    created_at = data.get("created_at", "")
    return messages, model_id, created_at


def session_preview(session_file: Path) -> str:
    """Return a one-line summary of a session for /history display."""
    try:
        with open(session_file) as f:
            data = json.load(f)
        msgs = data.get("messages", [])
        count = len(msgs)
        first = next((m["content"][:60] for m in msgs if m["role"] == "user"), "(empty)")
        ts = data.get("created_at", session_file.stem)[:19]
        return f"{ts}  ({count} msgs)  \"{first}\""
    except Exception:
        return session_file.stem

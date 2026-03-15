"""``nova chat`` — thin Click wrapper + CLI I/O layer around :class:`ChatSession`."""

import asyncio
import base64
import difflib
import json
import os
from pathlib import Path
import click
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
try:
    import readline  # noqa: F401 — enables cursor movement + history in input()
except ImportError:
    pass  # not available on Windows; safe to skip
from typing import Optional

from ..core import ChatSession, TurnCallbacks, DEFAULT_SYSTEM_PROMPT
from ..storage import (
    new_session_file,
    latest_session_file,
    list_session_files,
    load_session,
    session_preview,
    project_dir,
    load_nova_md,
)

HELP_TEXT = """\
Slash commands:
  /exit                         Quit the session
  /clear                        Clear history and start a new session
  /tools                        List available tools
  /auto-approve                 Toggle auto-approve on/off
  /history                      List past sessions for this project
  /thinking off|low|medium|high|auto  Set thinking effort for this session
  /file <path>[:<L1>-<L2>] msg        Attach file (or line range) as context
  /help                               Show this message\
"""


# ── File context builder ──────────────────────────────────────────────────────

def _build_file_context(path: str, line_start: int = None, line_end: int = None) -> str:
    """Read a file (or a slice of its lines) and return a formatted context block."""
    with open(path, errors="replace") as f:
        lines = f.readlines()

    if line_start is not None and line_end is not None:
        start = max(1, line_start)
        end = min(line_end, len(lines))
        selected = lines[start - 1 : end]
        content = "".join(selected)
        header = f"--- File: {path} (lines {start}-{end}) ---"
    else:
        content = "".join(lines)
        header = f"--- File: {path} ---"

    return f"{header}\n{content}\n---"


# ── Tool call label formatter ─────────────────────────────────────────────────

def _tool_label(name: str, args: dict) -> str:
    """Return a compact Claude Code-style label for a tool invocation."""
    a = args
    if name == "read_file":
        return f"Read    {a.get('path', '')}"
    if name == "write_file":
        return f"Write   {a.get('path', '')}"
    if name == "edit_file":
        return f"Edit    {a.get('path', '')}"
    if name == "multi_edit":
        return f"Edit    {a.get('path', '')}"
    if name == "bash":
        return f"Bash    {a.get('command', '')[:80]}"
    if name == "glob_files":
        return f"Glob    {a.get('pattern', '')}"
    if name == "grep":
        return f"Grep    {a.get('pattern', '')}  {a.get('path', '')}"
    if name == "list_directory":
        return f"LS      {a.get('path', '.')}"
    if name == "web_search":
        return f"Search  {a.get('query', '')}"
    if name == "web_fetch":
        return f"Fetch   {a.get('url', '')}"
    if name == "todo_read":
        return "Read    todos"
    if name == "todo_write":
        return "Write   todos"
    if name == "notebook_read":
        return f"Read    {a.get('path', '')}"
    if name == "notebook_edit":
        return f"Edit    {a.get('path', '')}"
    first_val = next(iter(a.values()), "") if a else ""
    return f"{name}  {str(first_val)[:80]}"


# ── Diff helpers ──────────────────────────────────────────────────────────────

_WRITE_TOOLS = {"write_file", "edit_file", "multi_edit"}
_MAX_DIFF_LINES = 60


def _print_diff(old_lines: list, new_lines: list, is_new: bool = False) -> None:
    """Print a coloured unified diff to the terminal."""
    if is_new:
        click.echo(click.style("  [new file]", dim=True))
        for line in new_lines[:_MAX_DIFF_LINES]:
            click.echo(click.style(f"  +{line.rstrip()}", fg="green"))
        if len(new_lines) > _MAX_DIFF_LINES:
            click.echo(click.style(
                f"  ... (+{len(new_lines) - _MAX_DIFF_LINES} more lines)", dim=True
            ))
        return

    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
    if not diff:
        click.echo(click.style("  (no changes)", dim=True))
        return

    shown = 0
    for line in diff:
        if shown >= _MAX_DIFF_LINES:
            click.echo(click.style(
                f"  ... ({len(diff) - shown} more diff lines)", dim=True
            ))
            break
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("+"):
            click.echo(click.style(f"  {line}", fg="green"))
        elif line.startswith("-"):
            click.echo(click.style(f"  {line}", fg="red"))
        else:
            click.echo(click.style(f"  {line}", dim=True))
        shown += 1


def _show_diff(name: str, args: dict) -> None:
    """Compute and display a diff for write/edit tool calls (best-effort)."""
    try:
        if name == "write_file":
            path = args.get("path", "")
            new_content = args.get("content", "")
            try:
                with open(path, errors="replace") as f:
                    old_lines = f.readlines()
            except FileNotFoundError:
                old_lines = []
            new_lines = new_content.splitlines(keepends=True)
            _print_diff(old_lines, new_lines, is_new=not old_lines)

        elif name == "edit_file":
            old = args.get("old_string", "")
            new = args.get("new_string", "")
            _print_diff(old.splitlines(keepends=True), new.splitlines(keepends=True))

        elif name == "multi_edit":
            edits_raw = args.get("edits", "[]")
            edits = json.loads(edits_raw) if isinstance(edits_raw, str) else edits_raw
            for i, edit in enumerate(edits):
                if i > 0:
                    click.echo()
                old = edit.get("old_string", "")
                new = edit.get("new_string", "")
                _print_diff(old.splitlines(keepends=True), new.splitlines(keepends=True))
    except Exception:
        pass  # diff display is best-effort — never break the approval flow


# ── CLI I/O implementation of TurnCallbacks ───────────────────────────────────

class CliCallbacks:
    """Implements :class:`TurnCallbacks` using rich Live + click for prompts.

    Nova text is accumulated and re-rendered as Markdown in a rich Live panel.
    Approval prompts stop the live display so the terminal is usable.
    All blocking I/O (``input()``) runs via ``asyncio.to_thread``.
    """

    def __init__(self) -> None:
        self._console = Console()
        self._buffer = ""
        self._live: Optional[Live] = None

    def _stop_live(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
            self._buffer = ""

    async def on_text(self, text: str) -> None:
        self._buffer += text
        if self._live is None:
            self._live = Live(
                Markdown(self._buffer),
                console=self._console,
                refresh_per_second=8,
            )
            self._live.start()
        else:
            self._live.update(Markdown(self._buffer))

    async def approve_tool(self, name: str, args: dict) -> bool:
        self._stop_live()
        click.echo(f"\n  {_tool_label(name, args)}")
        _show_diff(name, args)
        try:
            raw = await asyncio.to_thread(input, "  Approve? [Y/n]: ")
        except (EOFError, KeyboardInterrupt):
            raw = "n"
        return raw.strip().lower() not in ("n", "no")

    async def on_tool_result(self, name: str, args: dict, result: str) -> None:
        if name in _WRITE_TOOLS:
            click.echo(click.style("  ✓", fg="green"))
        elif name == "bash":
            lines = result.splitlines()
            preview = "\n    ".join(lines[:15])
            if preview:
                click.echo(f"\n    {preview}")
            if len(lines) > 15:
                click.echo(click.style(
                    f"    ... ({len(lines) - 15} more lines)", dim=True
                ))
        else:
            # Read-only tools: label was not shown before (no approval prompt),
            # so show it now as confirmation.
            click.echo(f"\n  {_tool_label(name, args)}")

    async def on_rejection(self, tool_name: str) -> str:
        self._stop_live()
        click.echo(f"\n['{tool_name}' rejected]")
        click.echo("  Enter to stop  |  'skip' to skip this step  |  or describe what you want instead")
        try:
            raw = await asyncio.to_thread(input, "Next steps: ")
        except (EOFError, KeyboardInterrupt):
            raw = "stop"
        return raw.strip() or "stop"

    async def on_turn_end(self) -> None:
        self._stop_live()
        click.echo()


# ── Session picker (CLI-only UI concern) ──────────────────────────────────────

def _pick_session():
    """Interactively prompt the user to choose a past session."""
    sessions = list_session_files()
    if not sessions:
        click.echo(f"No saved sessions found for {project_dir()}")
        return None

    click.echo(f"\nSaved sessions for {project_dir()}:")
    for i, s in enumerate(sessions, 1):
        click.echo(f"  {i}.  {session_preview(s)}")
    click.echo()

    try:
        raw = input("Enter session number (or press Enter to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if not raw:
        return None

    try:
        idx = int(raw) - 1
        if 0 <= idx < len(sessions):
            return sessions[idx]
        click.echo("Invalid selection.")
        return None
    except ValueError:
        click.echo("Invalid input.")
        return None


# ── Logo display ──────────────────────────────────────────────────────────────

def _print_logo() -> None:
    """Display the Nova Code logo using the iTerm2 inline image protocol.

    Supported terminals: iTerm2, WezTerm, VS Code integrated terminal.
    Silently skipped everywhere else so it never breaks the startup flow.
    """
    term = os.environ.get("TERM_PROGRAM", "")
    # ITERM_SESSION_ID is set by iTerm2 even when TERM_PROGRAM differs
    supported = (
        term in ("iTerm.app", "WezTerm", "vscode")
        or bool(os.environ.get("ITERM_SESSION_ID"))
    )
    if not supported:
        return
    img_path = Path(__file__).parents[3] / "novacode.png"
    if not img_path.exists():
        return
    try:
        data = base64.b64encode(img_path.read_bytes()).decode()
        # ESC ] 1337 ; File = ... : <base64> BEL
        print(
            f"\x1b]1337;File=inline=1;width=auto;height=5;preserveAspectRatio=1:{data}\a",
            flush=True,
        )
    except Exception:
        pass  # never break startup


# ── Async REPL ────────────────────────────────────────────────────────────────

async def _chat_async(do_continue, do_resume, disable_tools, thinking, auto_approve):
    from ..tools import all_tools

    tools = None if disable_tools else all_tools()

    nova_md_content, nova_md_files = load_nova_md()
    if nova_md_content:
        effective_system = (
            DEFAULT_SYSTEM_PROMPT
            + "\n\n--- Instructions from NOVA.md ---\n"
            + nova_md_content
        )
    else:
        effective_system = DEFAULT_SYSTEM_PROMPT

    created_at: Optional[str] = None
    seed_messages: list = []

    if do_resume:
        chosen = _pick_session()
        if chosen is None:
            return
        messages, _saved_model, created_at = load_session(chosen)
        seed_messages = messages
        session_file = chosen
        resume_info = f"Resuming session from {created_at[:19]}  ({len(messages)} messages)"

    elif do_continue:
        latest = latest_session_file()
        if latest is None:
            click.echo("No previous session found. Starting a new one.\n")
            session_file = new_session_file()
            resume_info = f"New session  →  {session_file}"
        else:
            messages, _saved_model, created_at = load_session(latest)
            seed_messages = messages
            session_file = latest
            resume_info = f"Resuming session from {created_at[:19]}  ({len(messages)} messages)"

    else:
        session_file = new_session_file()
        resume_info = f"New session  →  {session_file}"

    session = ChatSession(
        tools=tools,
        system=effective_system,
        session_file=session_file,
        seed_messages=seed_messages,
        created_at=created_at,
        thinking_effort=thinking,
        auto_approve=auto_approve,
    )
    callbacks = CliCallbacks()

    _print_logo()
    tools_status = f"{session.tools_count} tools" if tools else "tools disabled"
    approve_status = "  |  Auto-approve: ON" if auto_approve else ""
    click.echo(
        f"Nova Code  |  {session.model_id}"
        f"  |  Region: {session.region}"
        f"  |  {tools_status}"
        f"{approve_status}"
    )
    click.echo(resume_info)
    if nova_md_files:
        click.echo("NOVA.md: " + ", ".join(str(f) for f in nova_md_files))
    click.echo("Type /help for commands, /exit to quit.\n")

    while True:
        try:
            user_input = await asyncio.to_thread(input, "You: ")
            user_input = user_input.strip()
        except (EOFError, KeyboardInterrupt):
            click.echo("\nGoodbye!")
            break

        if not user_input:
            continue

        # ── Slash commands ──────────────────────────────────────────────────
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()

            if cmd == "/exit":
                click.echo("Goodbye!")
                break

            elif cmd == "/clear":
                session.clear()
                click.echo(f"[History cleared — new session: {session.session_file}]\n")

            elif cmd == "/tools":
                if not tools:
                    click.echo("[Tools are disabled (--no-tools)]\n")
                else:
                    click.echo("Available tools:")
                    for t in tools:
                        first_line = (t.description or "").splitlines()[0]
                        click.echo(f"  {t.name:<20}  {first_line}")
                    click.echo()

            elif cmd in ("/auto-approve", "/autoapprove"):
                session.auto_approve = not session.auto_approve
                state = "ON" if session.auto_approve else "OFF"
                click.echo(f"[Auto-approve: {state}]\n")

            elif cmd == "/thinking":
                level = parts[1].strip().lower() if len(parts) > 1 else ""
                valid = ("off", "low", "medium", "high", "auto")
                if level not in valid:
                    click.echo(f"[Usage: /thinking off|low|medium|high|auto]\n")
                    continue
                effort = None if level == "off" else level
                session.set_thinking(effort)
                click.echo(f"[Thinking: {level}]\n")

            elif cmd == "/history":
                sessions = list_session_files()
                if not sessions:
                    click.echo(f"[No saved sessions for {project_dir()}]\n")
                else:
                    click.echo(f"Sessions for {project_dir()}:")
                    for i, s in enumerate(sessions, 1):
                        marker = "  ← current" if s == session.session_file else ""
                        click.echo(f"  {i}.  {session_preview(s)}{marker}")
                    click.echo()

            elif cmd == "/file":
                rest = parts[1] if len(parts) > 1 else ""
                file_spec, _, user_message = rest.partition(" ")
                user_message = user_message.strip()
                if not file_spec or not user_message:
                    click.echo("[Usage: /file <path>[:<L1>-<L2>] <message>]\n")
                    continue

                file_path = file_spec
                line_start = line_end = None
                if ":" in file_spec:
                    maybe_path, _, range_str = file_spec.rpartition(":")
                    if "-" in range_str:
                        try:
                            s, e = range_str.split("-", 1)
                            line_start, line_end = int(s), int(e)
                            file_path = maybe_path
                        except ValueError:
                            pass

                try:
                    context = _build_file_context(file_path, line_start, line_end)
                except OSError as e:
                    click.echo(f"[Cannot read file: {e}]\n")
                    continue

                try:
                    await session.run_turn(user_message, callbacks, context=context)
                except (KeyboardInterrupt, asyncio.CancelledError):
                    session.cancel()
                    click.echo("\n[Interrupted]\n")
                except Exception as e:
                    click.echo(f"\nError: {e}\n", err=True)

            elif cmd == "/help":
                click.echo(HELP_TEXT + "\n")

            else:
                click.echo(f"Unknown command: {cmd}. Type /help.\n")

            continue

        # ── Regular message ─────────────────────────────────────────────────
        try:
            await session.run_turn(user_input, callbacks)
        except (KeyboardInterrupt, asyncio.CancelledError):
            session.cancel()
            click.echo("\n[Interrupted]\n")
        except Exception as e:
            click.echo(f"\nError: {e}\n", err=True)


# ── Click command ─────────────────────────────────────────────────────────────

@click.command(name="chat")
@click.option("--continue", "-c", "do_continue", is_flag=True, default=False,
              help="Continue the most recent session for this directory.")
@click.option("--resume", "-r", "do_resume", is_flag=True, default=False,
              help="Pick a past session to resume (interactive list).")
@click.option("--no-tools", "disable_tools", is_flag=True, default=False,
              help="Disable tool use (plain chat mode).")
@click.option(
    "--thinking",
    type=click.Choice(["low", "medium", "high", "auto"]),
    default=None,
    help="Enable extended thinking (low/medium/high) or let the model decide (auto).",
)
@click.option(
    "--auto-approve", "auto_approve", is_flag=True, default=False,
    help="Skip tool approval prompts — all tools run automatically.",
)
@click.pass_context
def chat_cmd(ctx, do_continue, do_resume, disable_tools, thinking, auto_approve):
    """Start an interactive chat session with Nova Code.

    \b
    nova chat                    Start a new session with tools (default)
    nova chat -c                 Continue the most recent session
    nova chat -r                 Pick a past session to resume
    nova chat --no-tools         Plain chat without tool access
    nova chat --thinking medium  Enable extended thinking
    nova chat --auto-approve     Skip tool approval prompts
    """
    asyncio.run(_chat_async(do_continue, do_resume, disable_tools, thinking, auto_approve))

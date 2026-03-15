"""JSON-lines stdio server for Nova Code.

The VS Code extension spawns ``python -m novacode serve`` and communicates
via newline-delimited JSON on stdin/stdout.

TypeScript → Python (stdin):
    {"type": "turn",                "input": "...", "cwd": "/path"}
    {"type": "approval",            "approved": true}
    {"type": "rejection_direction", "direction": "stop|skip|<instruction>"}
    {"type": "stop"}
    {"type": "clear"}
    {"type": "list_sessions"}
    {"type": "resume_session",      "path": "/abs/path/to/session.json"}
    {"type": "switch_thinking",     "effort": "auto"|"low"|"medium"|"high"|null}
    {"type": "set_auto_approve",    "enabled": true|false}
    {"type": "exit"}

Python → TypeScript (stdout):
    {"type": "ready"}
    {"type": "text",             "content": "..."}
    {"type": "tool_approval",    "name": "...", "args": {...}}
    {"type": "tool_result",      "name": "...", "args": {...}, "content": "..."}
    {"type": "rejection_prompt", "tool_name": "..."}
    {"type": "turn_end"}
    {"type": "cancelled"}
    {"type": "error",            "message": "..."}
    {"type": "sessions_list",    "sessions": [{"path":"...","title":"...","created_at":"..."}]}
    {"type": "session_resumed",  "path": "...", "messages": [{"role":"user"|"assistant","content":"..."}]}
    {"type": "thinking_switched","effort": "auto"|"low"|"medium"|"high"|null}
    {"type": "auto_approve_changed", "enabled": true|false}

Cancellation design
-------------------
Stdin is split into two queues by the pumper task:
  _control_q  — turn / stop / clear / exit / list_sessions / resume_session
  _approval_q — approval / rejection_direction

The main serve() loop drains _control_q exclusively.  StdioCallbacks reads
from _approval_q for per-turn interactive prompts.  This lets the main loop
see a "stop" message *while a turn task is running concurrently*, because
the turn task reads only from _approval_q and never blocks _control_q.

When stop arrives, the main loop calls session.cancel() (stops at the next
tool boundary) AND current_task.cancel() (raises CancelledError at the next
await inside the task, which may be mid-LLM-generation).
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage

from .session import ChatSession, TurnCallbacks, DEFAULT_SYSTEM_PROMPT
from ..client import ThinkingEffort
from ..tools import all_tools
from ..storage import load_nova_md, load_session, list_sessions_info

# Message types that belong to the approval sub-protocol (per-turn reads).
_APPROVAL_TYPES = {"approval", "rejection_direction"}


def _write(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


async def _pump_stdin(
    control_q: asyncio.Queue,
    approval_q: asyncio.Queue,
) -> None:
    """Read stdin lines and route them to the appropriate queue.

    approval / rejection_direction → approval_q  (consumed by StdioCallbacks)
    everything else                → control_q   (consumed by the serve loop)

    On EOF, sends None to both queues so any blocked reader unblocks cleanly.
    """
    while True:
        raw = await asyncio.to_thread(sys.stdin.readline)
        if not raw:
            # EOF — unblock both queues
            await control_q.put(None)
            await approval_q.put(None)
            break
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            _write({"type": "error", "message": f"Invalid JSON: {e}"})
            continue

        if msg.get("type") in _APPROVAL_TYPES:
            await approval_q.put(msg)
        else:
            await control_q.put(msg)


class StdioCallbacks:
    """TurnCallbacks implementation that speaks JSON-lines over stdio.

    approve_tool and on_rejection read from approval_q, which is populated
    exclusively with "approval" and "rejection_direction" messages.  The main
    serve loop reads from control_q and never competes with these reads.
    """

    def __init__(self, approval_q: asyncio.Queue) -> None:
        self._approval_q = approval_q

    async def _read_approval(self) -> Optional[dict]:
        """Pop the next approval message. Returns None on EOF."""
        return await self._approval_q.get()

    async def on_text(self, text: str) -> None:
        _write({"type": "text", "content": text})

    async def approve_tool(self, name: str, args: dict) -> bool:
        _write({"type": "tool_approval", "name": name, "args": args})
        msg = await self._read_approval()
        if msg is None:
            return False  # EOF
        return bool(msg.get("approved", False))

    async def on_tool_result(self, name: str, args: dict, result: str) -> None:
        _write({"type": "tool_result", "name": name, "args": args, "content": result})

    async def on_rejection(self, tool_name: str) -> str:
        _write({"type": "rejection_prompt", "tool_name": tool_name})
        msg = await self._read_approval()
        if msg is None:
            return "stop"
        return msg.get("direction", "stop")

    async def on_turn_end(self) -> None:
        # turn_end is written by the _run_turn wrapper in serve() so it can
        # emit cancelled + turn_end in the correct order.
        pass


async def serve(thinking_effort: ThinkingEffort = None, auto_approve: bool = False) -> None:
    """Run the Nova Code stdio server with concurrent turn cancellation.

    Architecture:
      - A background _pump_stdin task reads all stdin into two queues.
      - The main loop processes control messages (turn/stop/clear/...).
      - Each turn runs as a separate asyncio.Task so the main loop can
        immediately process a "stop" message even during LLM generation.
      - "stop" calls session.cancel() (tool boundary) + task.cancel()
        (next await point, including mid-LLM).
    """
    nova_md_content, _ = load_nova_md()
    if nova_md_content:
        system = (
            DEFAULT_SYSTEM_PROMPT
            + "\n\n--- Instructions from NOVA.md ---\n"
            + nova_md_content
        )
    else:
        system = DEFAULT_SYSTEM_PROMPT

    session = ChatSession(
        tools=all_tools(), system=system,
        thinking_effort=thinking_effort,
        auto_approve=auto_approve,
    )

    control_q: asyncio.Queue = asyncio.Queue()
    approval_q: asyncio.Queue = asyncio.Queue()
    callbacks = StdioCallbacks(approval_q)

    pumper = asyncio.create_task(_pump_stdin(control_q, approval_q))
    current_task: Optional[asyncio.Task] = None
    # Tracks the ChatSession actually used by current_task.  May differ from
    # `session` if resume_session reassigned it while a turn was running.
    active_session: Optional[ChatSession] = None

    _write({"type": "ready"})
    _write({"type": "auto_approve_changed", "enabled": session.auto_approve})

    try:
        while True:
            msg = await control_q.get()
            if msg is None:
                break  # EOF

            msg_type = msg.get("type")

            if msg_type == "turn":
                if current_task and not current_task.done():
                    _write({"type": "error", "message": "A turn is already in progress."})
                    continue

                cwd = msg.get("cwd")
                if cwd and os.path.isdir(cwd):
                    os.chdir(cwd)

                # Capture loop variables for the closure.
                input_text = msg.get("input", "")
                context = msg.get("context") or None
                active_session = session

                async def _run_turn(
                    _input=input_text,
                    _context=context,
                    _session=session,
                    _callbacks=callbacks,
                ):
                    """Run one turn; always writes turn_end (and cancelled if needed)."""
                    nonlocal active_session
                    try:
                        await _session.run_turn(_input, _callbacks, context=_context)
                    except asyncio.CancelledError:
                        # run_turn re-raises after cleanup — write events here.
                        _write({"type": "cancelled"})
                    except Exception as e:
                        import traceback
                        _write({
                            "type": "error",
                            "message": str(e) or traceback.format_exc(),
                        })
                    finally:
                        active_session = None
                        _write({"type": "turn_end"})

                current_task = asyncio.create_task(_run_turn())

            elif msg_type == "stop":
                # Two-level cancel:
                #   active_session.cancel() → stops at the next tool boundary
                #     (uses active_session, not session, to handle the case
                #      where resume_session reassigned session mid-turn)
                #   current_task.cancel() → raises CancelledError at the next
                #                           await (may be mid-LLM-generation)
                if active_session is not None:
                    active_session.cancel()
                if current_task and not current_task.done():
                    current_task.cancel()
                else:
                    # No active turn — nothing to cancel.
                    # Send turn_end only to re-sync UI if it somehow got stuck.
                    _write({"type": "turn_end"})

            elif msg_type == "clear":
                session.clear()
                _write({"type": "cleared"})

            elif msg_type == "switch_thinking":
                effort = msg.get("effort") or None  # null → None → off
                session.set_thinking(effort)
                _write({"type": "thinking_switched", "effort": session.thinking_effort})

            elif msg_type == "set_auto_approve":
                session.auto_approve = bool(msg.get("enabled", False))
                _write({"type": "auto_approve_changed", "enabled": session.auto_approve})

            elif msg_type == "list_sessions":
                _write({"type": "sessions_list", "sessions": list_sessions_info()})

            elif msg_type == "resume_session":
                if current_task and not current_task.done():
                    _write({"type": "error", "message": "Cannot resume session while a turn is in progress."})
                    continue
                path_str = msg.get("path", "")
                if path_str:
                    try:
                        messages, _saved_model, created_at = load_session(Path(path_str))
                        session = ChatSession(
                            tools=all_tools(),
                            system=system,
                            session_file=Path(path_str),
                            seed_messages=messages,
                            created_at=created_at,
                            thinking_effort=session.thinking_effort,
                            auto_approve=session.auto_approve,
                        )
                        ui_messages = []
                        for m in messages:
                            if isinstance(m, HumanMessage):
                                content = m.content if isinstance(m.content, str) else ""
                                ui_messages.append({"role": "user", "content": content})
                            elif isinstance(m, AIMessage):
                                if isinstance(m.content, list):
                                    content = " ".join(
                                        b.get("text", "") for b in m.content
                                        if isinstance(b, dict) and b.get("type") == "text"
                                    )
                                else:
                                    content = m.content if isinstance(m.content, str) else ""
                                if content:
                                    ui_messages.append({"role": "assistant", "content": content})
                        _write({"type": "session_resumed", "path": path_str, "messages": ui_messages})
                    except Exception as e:
                        _write({"type": "error", "message": f"Failed to resume session: {e}"})

            elif msg_type == "exit":
                break

    finally:
        pumper.cancel()
        if current_task and not current_task.done():
            current_task.cancel()

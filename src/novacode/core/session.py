"""Core chat session — no Click, no I/O framework dependencies."""

import asyncio
import threading
import uuid
from pathlib import Path
from typing import Optional
from typing_extensions import Protocol

from langchain.agents import create_agent
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool

from ..client import NovaClient
from ..tools import READ_ONLY_TOOLS
from ..storage import (
    new_session_file,
    save_session,
    slugify,
)


DEFAULT_SYSTEM_PROMPT = """\
You are Nova Code, an AI coding assistant. You help users write, explain, \
debug, and refactor code. Be concise and practical. Use markdown for code blocks.

You have access to tools. Follow these rules for tool selection:

PREFER these tools for reading and exploration (they run without user approval):
- read_file      — read any file
- grep           — search file contents with a regex pattern
- glob_files     — find files by name/path pattern
- list_directory — list directory contents
- web_search     — search the web
- web_fetch      — fetch a URL

RESERVE bash for operations that actually execute, install, or mutate state \
(running tests, starting servers, installing packages, etc.). \
Never use bash just to grep, cat, find, or ls — use the dedicated tools above instead.

EDITOR CONTEXT RULES: You may receive an "Editor context" section below. \
This is ambient information about the file currently open in the user's editor. \
Do NOT explain, summarize, or comment on it unless the user's message \
explicitly asks about it. Treat it as background awareness only.\
"""


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_text_from_chunk(chunk) -> str:
    """Extract text from a streaming AIMessageChunk, skipping tool/reasoning blocks."""
    content = chunk.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
            and block.get("type", "text") == "text"
            and block.get("text")
        )
    return ""


# ── Callback interface ────────────────────────────────────────────────────────

class TurnCallbacks(Protocol):
    """Async interface between the core session logic and any I/O layer."""

    async def on_text(self, text: str) -> None:
        """Called with streaming text tokens as they are generated."""

    async def approve_tool(self, name: str, args: dict) -> bool:
        """Called before a write/exec tool runs. Return True to approve."""

    async def on_tool_result(self, name: str, args: dict, result: str) -> None:
        """Called after a tool executes with the tool name, its args, and result."""

    async def on_rejection(self, tool_name: str) -> str:
        """Called when the user rejects a tool call.

        Return ``""``/``"stop"`` to abort, or any other string as new instructions.
        """

    async def on_turn_end(self) -> None:
        """Called once at the very end of a completed turn."""


# ── Per-turn approval state ───────────────────────────────────────────────────

class _TurnState:
    """Shared state between approval-wrapped tools within one agent turn.

    When any tool is rejected, ``stop`` is set so remaining tools in the
    same parallel batch return ``[Cancelled]`` immediately.
    """
    __slots__ = ("stop",)

    def __init__(self) -> None:
        self.stop: bool = False


# ── Tool wrapper ──────────────────────────────────────────────────────────────

def _wrap_tool(
    tool,
    callbacks: TurnCallbacks,
    state: _TurnState,
    cancel_event: threading.Event,
    auto_approve: bool = False,
) -> StructuredTool:
    """Wrap a tool with async approval logic before execution.

    - Read-only tools execute immediately in a thread (no approval needed).
    - When ``auto_approve`` is True, write/exec tools run without asking.
    - Otherwise write / exec tools pause and ask via ``callbacks.approve_tool``.
    - On rejection, ``callbacks.on_rejection`` asks what to do next.
    - If ``cancel_event`` is set the tool returns ``[Cancelled]`` immediately.
    """
    name = tool.name

    async def _run_async(**kwargs):
        if state.stop or cancel_event.is_set():
            return "[Cancelled]"

        if name in READ_ONLY_TOOLS:
            try:
                result = str(await asyncio.to_thread(tool.invoke, kwargs))
            except Exception as e:
                result = f"Error in {name}: {e}"
            await callbacks.on_tool_result(name, kwargs, result)
            return result

        approved = auto_approve or await callbacks.approve_tool(name, kwargs)
        if approved:
            try:
                result = str(await asyncio.to_thread(tool.invoke, kwargs))
            except Exception as e:
                result = f"Error in {name}: {e}"
            await callbacks.on_tool_result(name, kwargs, result)
            return result

        direction = (await callbacks.on_rejection(name) or "stop").strip()
        state.stop = True  # cancel remaining tools in this batch

        if not direction or direction.lower() == "stop":
            return "[Rejected by user — stopping this turn]"

        return f"[Tool rejected — user redirected: {direction}]"

    def _run(**kwargs):
        # Sync fallback for non-async callers (e.g. tests).
        # Not reachable during normal async agent execution — LangGraph calls
        # _run_async directly via ainvoke when the coroutine is registered.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            # Already inside an event loop (e.g. pytest-asyncio, Jupyter).
            # Schedule the coroutine and block via a concurrent future.
            fut = asyncio.run_coroutine_threadsafe(_run_async(**kwargs), loop)
            return fut.result(timeout=300)
        return asyncio.run(_run_async(**kwargs))

    return StructuredTool.from_function(
        func=_run,
        coroutine=_run_async,
        name=name,
        description=tool.description,
        args_schema=tool.args_schema,
    )


# ── ChatSession ───────────────────────────────────────────────────────────────

class ChatSession:
    """A single Nova Code chat session backed by ``langchain.agents.create_agent``.

    The agentic loop (LLM → tools → LLM) is driven by ``astream_events`` for
    real-time token streaming.  Tool approval / rejection logic lives entirely
    inside ``_wrap_tool``, keeping ``_run_agentic_turn`` simple.

    Cancellation:
        Call ``session.cancel()`` from any thread to stop at the next tool
        boundary.  Does not interrupt a mid-flight LLM generation, but prevents
        any further tool calls from running.
    """

    def __init__(
        self,
        tools: Optional[list] = None,
        system: Optional[str] = None,
        session_file: Optional[Path] = None,
        seed_messages: Optional[list] = None,
        created_at: Optional[str] = None,
        thinking_effort: Optional[str] = None,
        max_iterations: int = 100,
        auto_approve: bool = False,
    ):
        # "auto" is handled at the session layer — never passed to the client.
        self._auto_thinking: bool = (thinking_effort == "auto")
        client_effort = None if self._auto_thinking else thinking_effort
        self._client = NovaClient(thinking_effort=client_effort)  # type: ignore[arg-type]
        self._tools = tools or []
        self._system = system or DEFAULT_SYSTEM_PROMPT
        self._session_file = session_file or new_session_file()
        self._seed_messages: list = seed_messages or []
        self._created_at = created_at
        self._first_turn = True
        self._max_iterations = max_iterations
        self._auto_approve = auto_approve
        # Thread-safe: can be set from any thread (e.g. a stop button handler).
        self._cancel_event = threading.Event()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def model_id(self) -> str:
        return self._client.model_id

    @property
    def region(self) -> str:
        return self._client.region

    @property
    def session_file(self) -> Path:
        return self._session_file

    @property
    def tools_count(self) -> int:
        return len(self._tools)

    @property
    def thinking_effort(self) -> Optional[str]:
        if self._auto_thinking:
            return "auto"
        return self._client.thinking_effort

    @property
    def auto_approve(self) -> bool:
        return self._auto_approve

    @auto_approve.setter
    def auto_approve(self, value: bool) -> None:
        self._auto_approve = value

    def cancel(self) -> None:
        """Signal the current turn to stop at the next tool boundary.

        Thread-safe — can be called from any thread.  Takes effect before the
        next tool invocation; does not interrupt an in-progress LLM generation.
        """
        self._cancel_event.set()

    async def run_turn(
        self,
        user_input: str,
        callbacks: TurnCallbacks,
        context: str = None,
    ) -> None:
        """Execute one user turn, firing callbacks for all events.

        ``context`` is optional editor context (open file, selection) appended
        to the system prompt for this turn only.  It is never stored in
        history and never part of the user message — the LLM sees it as
        ambient background awareness.
        """
        self._cancel_event.clear()

        if self._first_turn:
            for msg in self._seed_messages:
                self._client.history.add_message(msg)
            self._first_turn = False
            if not self._seed_messages:
                slug = slugify(user_input)
                uid = uuid.uuid4().hex[:8]
                self._session_file = self._session_file.parent / f"{slug}-{uid}.json"

        if self._tools:
            await self._run_agentic_turn(user_input, callbacks, context=context)
        else:
            # Plain-chat path: stream directly from the LLM, no tool loop.
            # Context goes into the system prompt, NOT the user message.
            turn_system = self._build_turn_system(context)
            llm_messages = []
            if turn_system:
                llm_messages.append(SystemMessage(content=turn_system))
            llm_messages.extend(self._client.history.messages)
            llm_messages.append(HumanMessage(content=user_input))
            full_response = ""

            # Run the synchronous boto3 stream in a background thread so the
            # event loop stays responsive between chunks (stop messages can be
            # processed while waiting for the next token).
            #
            # Pattern: thread pushes chunks via call_soon_threadsafe; async
            # consumer awaits each item from the queue, yielding to the event
            # loop between chunks.  This is the only safe way to interleave a
            # sync generator with an async event loop.
            chunk_q: asyncio.Queue = asyncio.Queue()
            _DONE = object()  # sentinel
            _loop = asyncio.get_running_loop()

            def _sync_stream() -> None:
                try:
                    for chunk in self._client.llm.stream(llm_messages):
                        _loop.call_soon_threadsafe(chunk_q.put_nowait, chunk)
                except Exception as exc:
                    _loop.call_soon_threadsafe(chunk_q.put_nowait, exc)
                finally:
                    _loop.call_soon_threadsafe(chunk_q.put_nowait, _DONE)

            # Start the thread concurrently; do NOT await yet.
            stream_task = asyncio.create_task(asyncio.to_thread(_sync_stream))
            try:
                while True:
                    item = await chunk_q.get()
                    if item is _DONE:
                        break
                    if isinstance(item, Exception):
                        raise item
                    text = _extract_text_from_chunk(item)
                    if text:
                        full_response += text
                        await callbacks.on_text(text)
            finally:
                # Always join the background task (handles cancellation too).
                await stream_task

            self._client.history.add_user_message(user_input)
            self._client.history.add_ai_message(full_response)
            await callbacks.on_turn_end()
            save_session(
                self._session_file,
                self._client.history.messages,
                self._client.model_id,
                self._created_at,
            )

    def set_thinking(self, effort: Optional[str]) -> None:
        if effort == "auto":
            if self._auto_thinking:
                return
            self._auto_thinking = True
            self._client.set_thinking(None)
        else:
            self._auto_thinking = False
            if self._client.thinking_effort != effort:
                self._client.set_thinking(effort)  # type: ignore[arg-type]

    def clear(self) -> None:
        self._client.clear_history()
        self._session_file = new_session_file()
        self._seed_messages = []
        self._first_turn = True
        self._created_at = None

    # ── Internals ─────────────────────────────────────────────────────────────

    def _build_turn_system(self, context: Optional[str] = None) -> str:
        """Build the system prompt for a single turn.

        The base ``self._system`` is always included.  When ``context`` is
        provided (open file / selection from the editor) it is appended as a
        clearly-labelled ambient section that the LLM should NOT explain
        unless the user explicitly asks.
        """
        if not context:
            return self._system
        return (
            self._system
            + "\n\n--- Editor context (ambient — reference only if the user asks) ---\n"
            + context
        )

    async def _auto_classify_effort(self, user_input: str) -> str:
        """Classify task complexity with a cheap single LLM call (auto mode only).

        Uses a no-thinking invocation so the classification is fast regardless
        of whatever thinking level may be set from a previous turn.  Returns
        one of ``"low"``, ``"medium"``, or ``"high"``, falling back to
        ``"medium"`` on any error or unexpected response.
        """
        classifier = ChatBedrockConverse(
            model=self._client.model_id,
            region_name=self._client.region,
            temperature=0.1,
            max_tokens=10,
        )
        msgs = [
            SystemMessage(content=(
                "Classify this coding task. Reply with exactly one word: "
                "low, medium, or high.\n"
                "low=simple question or quick lookup.\n"
                "medium=coding task, debugging, multi-file changes.\n"
                "high=complex refactor, architecture, algorithms, system design."
            )),
            HumanMessage(content=user_input[:400]),
        ]
        try:
            response = await asyncio.to_thread(classifier.invoke, msgs)
            text = (response.content or "").strip().lower() if isinstance(response.content, str) else ""
            word = text.split()[0] if text else "medium"
            return word if word in ("low", "medium", "high") else "medium"
        except Exception:
            return "medium"

    async def _run_agentic_turn(
        self,
        user_input: str,
        callbacks: TurnCallbacks,
        context: str = None,
    ) -> None:
        """Run one turn through create_agent with astream_events for token streaming.

        Text tokens are emitted to ``callbacks.on_text`` as they arrive from the
        LLM — no buffering, real-time display.  Tool approval / rejection happen
        inside each wrapped tool's async coroutine, keeping the event loop
        responsive throughout the entire turn.

        ``user_input`` is NOT added to history until the turn completes
        successfully.  This prevents orphaned user messages if the turn is
        cancelled before any AI response is captured.  On success, the user
        message is part of ``all_final_messages`` and persisted along with the
        agent's response in one atomic write.
        """
        state = _TurnState()

        # In auto mode: classify task complexity BEFORE building the agent so the
        # correct thinking level is applied to the current turn's LLM, not the next.
        if self._auto_thinking:
            effort = await self._auto_classify_effort(user_input)
            self._client.set_thinking(effort)  # type: ignore[arg-type]
            await callbacks.on_tool_result(
                "set_thinking_mode", {"level": effort}, f"Thinking mode set to {effort}."
            )

        wrapped = [_wrap_tool(t, callbacks, state, self._cancel_event, self._auto_approve) for t in self._tools]

        # Build a per-turn system prompt with editor context appended (if any).
        turn_system = self._build_turn_system(context)

        agent = create_agent(
            self._client.llm,
            tools=wrapped,
            system_prompt=turn_system,
        )

        # Build initial messages without touching history yet.
        # Context lives in the system prompt, so the user message is always clean.
        current_history = list(self._client.history.messages)
        initial_messages = current_history + [HumanMessage(content=user_input)]

        streamed_text = False
        was_cancelled = False
        # The last on_chain_end whose messages list is longer than initial_messages
        # is the complete accumulated graph state — used for history persistence.
        all_final_messages: Optional[list] = None

        try:
            async for event in agent.astream_events(
                {"messages": initial_messages},
                config={"recursion_limit": self._max_iterations},
                version="v2",
            ):
                if self._cancel_event.is_set():
                    break

                kind = event["event"]

                if kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if chunk:
                        text = _extract_text_from_chunk(chunk)
                        if text:
                            await callbacks.on_text(text)
                            streamed_text = True

                elif kind == "on_chain_end":
                    output = event["data"].get("output")
                    if isinstance(output, dict) and "messages" in output:
                        msgs = output["messages"]
                        if len(msgs) > len(initial_messages):
                            all_final_messages = msgs

        except asyncio.CancelledError:
            # Re-raised below after cleanup — do NOT swallow permanently.
            # Caller (chat.py except block, stdio _run_turn finally) handles I/O.
            was_cancelled = True

        if not streamed_text and not was_cancelled:
            await callbacks.on_text(
                "[No response text received — the model may have produced "
                "only internal reasoning. Try rephrasing or toggling thinking off.]"
            )

        # on_turn_end is skipped when cancelled — the caller owns that event
        # so it can write `cancelled` + `turn_end` in the correct order.
        if not was_cancelled:
            await callbacks.on_turn_end()

        # Persist to history only on a complete (non-cancelled) turn.
        # new_messages = everything after current_history, which includes the
        # user message + all agent messages (AI responses + tool results).
        # Context lives in the system prompt so user messages are already clean
        # — no stripping needed.
        if all_final_messages:
            new_messages = list(all_final_messages[len(current_history):])
            for msg in new_messages:
                self._client.history.add_message(msg)

        save_session(
            self._session_file,
            self._client.history.messages,
            self._client.model_id,
            self._created_at,
        )

        # Re-raise after all cleanup so callers can write cancelled/turn_end
        # events in the correct order and so Python's task cancellation
        # machinery knows the cancellation was handled (not silently swallowed).
        if was_cancelled:
            raise asyncio.CancelledError()

"""Core single-shot ask logic — no Click, no I/O."""

from typing import Iterator, List, Optional

from ..client import NovaClient, ThinkingEffort
from ..storage import load_nova_md


def run_ask(
    prompt: str,
    files: Optional[List[str]] = None,
    system: Optional[str] = None,
    thinking_effort: Optional[ThinkingEffort] = None,
) -> Iterator[str]:
    """Ask Nova a single question and stream back the response.

    This is the pure-logic counterpart to the ``nova ask`` CLI command.
    It has no dependency on Click, stdin, or any I/O framework — callers
    receive an iterator of text chunks and decide how to display them.

    Args:
        prompt:           The question or instruction to send.
        files:            Optional list of file paths whose contents are
                          prepended as context blocks.
        system:           Override the system prompt.  When None the
                          global/project NOVA.md is used if present.
        thinking_effort:  Extended thinking level: "low", "medium", or "high".
                          None (default) disables extended thinking.

    Yields:
        Text chunks from the streaming model response.
    """
    client = NovaClient(thinking_effort=thinking_effort)

    # Build effective system prompt (NOVA.md takes precedence when present)
    if system is None:
        nova_md_content, _ = load_nova_md()
        if nova_md_content:
            system = "--- Instructions from NOVA.md ---\n" + nova_md_content

    # Prepend file contents as context blocks
    parts: List[str] = []
    for path in (files or []):
        with open(path) as fh:
            parts.append(f"--- {path} ---\n{fh.read()}")

    full_prompt = "\n\n".join(parts) + "\n\n" + prompt if parts else prompt

    yield from client.ask_once(full_prompt, system=system)

"""``nova ask`` — thin Click wrapper around :func:`novacode.core.run_ask`."""

import sys
import click

from ..core import run_ask


@click.command(name="ask")
@click.argument("prompt", required=False)
@click.option(
    "--file", "-f", "files",
    multiple=True,
    type=click.Path(exists=True),
    help="File(s) to include as context (repeatable).",
)
@click.option(
    "--thinking",
    type=click.Choice(["low", "medium", "high", "auto"]),
    default=None,
    help="Enable extended thinking (low/medium/high) or let the model decide (auto).",
)
@click.pass_context
def ask_cmd(ctx, prompt, files, thinking):
    """Ask Nova a single question (non-interactive).

    PROMPT can also be supplied via stdin:

        echo "explain this" | nova ask --file main.py
    """
    if not prompt:
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
        else:
            raise click.UsageError("Provide a PROMPT argument or pipe input via stdin.")

    try:
        from rich.console import Console
        from rich.markdown import Markdown
        buffer = ""
        for chunk in run_ask(
            prompt, files=list(files), thinking_effort=thinking
        ):
            buffer += chunk
        Console().print(Markdown(buffer))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

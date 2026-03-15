"""``nova serve`` — JSON-lines stdio server for the VS Code extension."""

import click


@click.command(name="serve")
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
def serve_cmd(ctx, thinking, auto_approve):
    """Run Nova Code as a JSON-lines stdio server.

    Used by the VS Code extension to communicate with the Python core.
    Not intended for direct interactive use.
    """
    import asyncio
    from ..core.stdio import serve

    asyncio.run(serve(thinking_effort=thinking, auto_approve=auto_approve))

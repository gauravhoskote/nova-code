import click
from .commands.ask import ask_cmd
from .commands.chat import chat_cmd
from .commands.serve import serve_cmd


@click.group()
@click.version_option("0.1.0", prog_name="Nova Code")
@click.pass_context
def main(ctx):
    """Nova Code - AI coding assistant powered by Amazon Bedrock Nova models."""
    ctx.ensure_object(dict)


main.add_command(ask_cmd)
main.add_command(chat_cmd)
main.add_command(serve_cmd)

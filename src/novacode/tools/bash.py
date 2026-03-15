import subprocess
from langchain_core.tools import tool
from . import register

MAX_OUTPUT = 8_000  # chars — keeps context window from exploding


@tool
def bash(command: str, timeout: int = 30) -> str:
    """Execute a shell command and return its combined stdout and stderr.

    Args:
        command: The shell command to run.
        timeout: Maximum seconds to wait before killing the process (default 30).

    Use for running tests, builds, git commands, or any terminal operation.
    Returns the command output or an error/timeout message.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        if not output:
            return f"(exit code {result.returncode}, no output)"

        if len(output) > MAX_OUTPUT:
            output = output[:MAX_OUTPUT] + f"\n... [truncated — {len(output)} chars total]"

        return output.rstrip()
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error running command: {e}"


register(bash)

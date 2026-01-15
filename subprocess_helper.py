import shlex
import subprocess
from typing import Iterable, Sequence

from DiscordMethod import send_discord_message


def _format_command(command: Sequence[str] | str) -> str:
    if isinstance(command, str):
        return command
    return " ".join(shlex.quote(str(p)) for p in command)


def run_logged_subprocess(command: Sequence[str] | str, **kwargs: object) -> subprocess.CompletedProcess:
    """Run a subprocess and emit failures to Discord."""
    try:
        send_discord_message(f"⚙️ subprocess: {_format_command(command)}")
        return subprocess.run(command, **kwargs)
    except subprocess.CalledProcessError as exc:
        
        err_text = (exc.stderr or exc.stdout or "").strip()
        msg = f"❌ subprocess failed ({exc.returncode})"
        if err_text:
            msg += f": {err_text[:1024]}"
        send_discord_message(msg)
        raise
    except Exception as exc:
        send_discord_message(f"❌ subprocess error: {exc}")
        raise

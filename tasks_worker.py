import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def start_periodic_task(coro_func, interval_seconds: int):
    """Start an asyncio background task that runs `coro_func()` every interval_seconds.

    `coro_func` should be an async callable that performs the maintenance work.
    Returns the created asyncio.Task so the caller can cancel if needed.
    """
    async def _runner():
        while True:
            try:
                await coro_func()
            except Exception:
                logger.exception("Error running periodic task")
            await asyncio.sleep(interval_seconds)

    task = asyncio.create_task(_runner())
    return task


async def run_in_executor(loop, func, *args, **kwargs):
    """Run a blocking function in the default executor and return result."""
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

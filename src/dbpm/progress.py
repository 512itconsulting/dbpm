from __future__ import annotations

import sys
from typing import TextIO


def report_progress(message: str, *, stream: TextIO | None = None) -> None:
    """Emit a concise human-readable progress message without using stdout."""
    destination = stream if stream is not None else sys.stderr
    print(f"dbpm: {message}", file=destination, flush=True)

"""Helpers that make stages resumable and idempotent.

A stage output is "fresh" when it exists and is newer than every input, so a
re-run only processes new or changed papers. Outputs are written atomically
(temp file + rename) so an interrupted run never leaves a half-written file
that would later look fresh.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def is_fresh(output: Path, *inputs: Path) -> bool:
    """True if ``output`` exists and is at least as new as every input."""
    try:
        out_mtime = output.stat().st_mtime
    except FileNotFoundError:
        return False
    return all(p.stat().st_mtime <= out_mtime for p in inputs)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path, data: Any) -> None:
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")

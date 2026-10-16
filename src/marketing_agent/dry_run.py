"""Append blocked and dry-run comments to a local JSONL audit file."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path


def save_comment(path: str | Path, *, video_id: str, body: str, reason: str, run_id: str, input_source: str) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "video_id": video_id, "body": body, "reason": reason,
        "run_id": run_id, "input_source": input_source,
    }
    with target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return str(target)

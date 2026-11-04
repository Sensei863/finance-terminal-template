import json
import os
import tempfile
from pathlib import Path

def atomic_write_json(file_path: Path, data: dict | list, indent: int = 2) -> None:
    """Atomically write data as JSON to file_path to prevent file truncation or corruption on crash."""
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temporary file in the same directory to ensure atomic rename on same volume
    temp_fd, temp_path = tempfile.mkstemp(dir=file_path.parent, prefix="tmp_", suffix=".json")
    try:
        with open(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, default=str)
        os.replace(temp_path, file_path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise

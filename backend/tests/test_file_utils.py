import pytest
import json
from pathlib import Path
from backend.services.file_utils import atomic_write_json

def test_atomic_write_json(tmp_path: Path):
    target = tmp_path / "sub" / "test_data.json"
    data = {"name": "Aegis", "status": "active", "value": 123.45}
    
    # Write initial data
    atomic_write_json(target, data)
    assert target.exists()
    
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == data
    
    # Overwrite data atomically
    new_data = {"name": "Aegis", "status": "updated", "value": 999.0}
    atomic_write_json(target, new_data)
    
    updated = json.loads(target.read_text(encoding="utf-8"))
    assert updated == new_data

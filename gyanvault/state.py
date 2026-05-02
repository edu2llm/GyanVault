import json
from pathlib import Path

from .config import STATE_FILE


class ProcessingState:
    def __init__(self, state_file: Path = STATE_FILE):
        self.state_file = state_file
        self.pass1_completed, self.pass2_completed = self.load()

    def load(self):
        if self.state_file.exists():
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("pass1_completed_ids", [])), set(data.get("pass2_completed_ids", []))
        return set(), set()

    def save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "pass1_completed_ids": list(self.pass1_completed),
            "pass2_completed_ids": list(self.pass2_completed),
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

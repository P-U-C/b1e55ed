import json
import os
from pathlib import Path

CONFIG_PATH = Path.home() / ".pf-scout" / "config.json"


def load_token() -> str:
    if os.environ.get("PF_JWT_TOKEN"):
        return os.environ["PF_JWT_TOKEN"]
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text()).get("jwt_token", "")
        except Exception:
            pass
    return ""


def save_token(token: str):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"jwt_token": token}, indent=2))

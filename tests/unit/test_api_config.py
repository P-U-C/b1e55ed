from __future__ import annotations

from pathlib import Path

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_config_read_validate_save(temp_dir, test_config, monkeypatch):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})

    # Ensure cwd is temp_dir so api routes write there
    monkeypatch.chdir(temp_dir)
    (temp_dir / "config").mkdir(parents=True, exist_ok=True)
    (temp_dir / "config" / "default.yaml").write_text("preset: balanced\n")

    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    headers = {"Authorization": "Bearer secret"}
    async with make_client(app) as ac:
        r = await ac.get("/api/v1/config", headers=headers)
        assert r.status_code == 200
        js = r.json()
        assert js["preset"] == test_config.preset

        r2 = await ac.post("/api/v1/config/validate", headers=headers, json=js)
        assert r2.status_code == 200
        assert r2.json()["ok"] is True

        js["brain"]["cycle_interval_seconds"] = 123
        r3 = await ac.post("/api/v1/config", headers=headers, json=js)
        assert r3.status_code == 200
        path = Path(r3.json()["path"])
        assert path.exists()

    app.state.db.close()

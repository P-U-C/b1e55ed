from __future__ import annotations

import pytest

from api.errors import B1e55edError
from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_b1e55ed_error_handler_json_shape(temp_dir, test_config):
    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    @app.get("/api/v1/_test/error")
    def _raise() -> None:
        raise B1e55edError(code="test.error", message="boom", status=418, detail="extra")

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/_test/error")
        assert r.status_code == 418
        js = r.json()
        assert js == {"error": {"code": "test.error", "message": "boom", "detail": "extra"}}

    app.state.db.close()


@pytest.mark.anyio
async def test_b1e55ed_error_handler_status_codes(temp_dir, test_config):
    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    @app.get("/api/v1/_test/notfound")
    def _notfound() -> None:
        raise B1e55edError(code="x.not_found", message="missing", status=404)

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/_test/notfound")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "x.not_found"

    app.state.db.close()

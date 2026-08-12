"""Tests for backend.services.data_format — the format-version stamp that
refuses writes from an older app onto newer data — and the middleware in
backend.app that enforces it."""
import json

from fastapi.testclient import TestClient

from backend.services import data_format


def _stamp_path(tmp_path):
    return tmp_path / "data" / "format.json"


def test_ensure_stamp_empty_root_writes_current(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))

    result = data_format.ensure_stamp("1.2.3")

    assert result["found"] is None
    assert result["current"] == data_format.CURRENT_FORMAT
    assert result["compatible"] is True

    stamp = json.loads(_stamp_path(tmp_path).read_text())
    assert stamp["format_version"] == data_format.CURRENT_FORMAT
    assert stamp["app_version"] == "1.2.3"
    assert "stamped_at" in stamp


def test_ensure_stamp_older_version_rewritten_to_current(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "format.json").write_text(
        json.dumps(
            {
                "format_version": 0,
                "app_version": "0.0.1",
                "stamped_at": "2020-01-01T00:00:00+00:00",
            }
        )
    )

    result = data_format.ensure_stamp("1.2.3")

    assert result["found"] == 0
    assert result["current"] == data_format.CURRENT_FORMAT
    assert result["compatible"] is True

    stamp = json.loads(_stamp_path(tmp_path).read_text())
    assert stamp["format_version"] == data_format.CURRENT_FORMAT
    assert stamp["app_version"] == "1.2.3"


def test_ensure_stamp_newer_version_left_untouched(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    stamp_file = data_dir / "format.json"
    newer = data_format.CURRENT_FORMAT + 1
    stamp_file.write_text(
        json.dumps(
            {
                "format_version": newer,
                "app_version": "9.9.9",
                "stamped_at": "2099-01-01T00:00:00+00:00",
            }
        )
    )
    original_bytes = stamp_file.read_bytes()

    result = data_format.ensure_stamp("1.2.3")

    assert result["found"] == newer
    assert result["current"] == data_format.CURRENT_FORMAT
    assert result["compatible"] is False
    assert stamp_file.read_bytes() == original_bytes


def test_ensure_stamp_corrupt_file_rewritten(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "format.json").write_text("{not valid json")

    result = data_format.ensure_stamp("1.2.3")

    assert result["found"] is None
    assert result["compatible"] is True

    stamp = json.loads(_stamp_path(tmp_path).read_text())
    assert stamp["format_version"] == data_format.CURRENT_FORMAT


def test_middleware_blocks_writes_when_format_incompatible(monkeypatch, tmp_path):
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path))
    import backend.app as app_module

    # Force the module-level startup result directly, rather than going
    # through lifespan — TestClient without `with` never runs lifespan
    # (see backend/app.py's DATA_FORMAT_STATE default comment).
    monkeypatch.setattr(
        app_module,
        "DATA_FORMAT_STATE",
        {"found": 99, "current": data_format.CURRENT_FORMAT, "compatible": False},
    )
    client = TestClient(app_module.app)

    write_resp = client.put(
        "/api/profile",
        json={"stage": "highschool", "name": "Test"},
    )
    assert write_resp.status_code == 409
    assert write_resp.json()["error"] == "data_format_newer"

    read_resp = client.get("/api/profile")
    assert read_resp.status_code == 200

    meta_resp = client.get("/api/meta")
    assert meta_resp.status_code == 200
    assert "data_format" in meta_resp.json()

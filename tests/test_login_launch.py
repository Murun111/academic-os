"""Start-at-login LaunchAgent plist + headless flag for serve_frozen (F65)."""
import importlib.util
from pathlib import Path

from backend.services import login_launch


def test_plist_sets_no_browser_env(monkeypatch, tmp_path):
    monkeypatch.setattr(login_launch, "_plist_path", lambda: tmp_path / "x.plist")
    monkeypatch.setattr(login_launch, "_program_args", lambda: ["/bin/true"])
    monkeypatch.setattr(login_launch.subprocess, "run", lambda *a, **k: None)
    assert login_launch.enable()["ok"]
    txt = (tmp_path / "x.plist").read_text()
    assert "<key>ACADEMIC_OS_NO_BROWSER</key><string>1</string>" in txt


def _load_serve_frozen():
    p = Path(__file__).resolve().parent.parent / "scripts" / "serve_frozen.py"
    spec = importlib.util.spec_from_file_location("serve_frozen_t", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_serve_frozen_honours_no_browser(monkeypatch):
    monkeypatch.setenv("ACADEMIC_OS_NO_BROWSER", "1")
    m = _load_serve_frozen()
    opened = []
    monkeypatch.setattr(m.webbrowser, "open", lambda u: opened.append(u))
    m._open_browser()
    assert opened == []
    monkeypatch.delenv("ACADEMIC_OS_NO_BROWSER")
    m2 = _load_serve_frozen()
    monkeypatch.setattr(m2.webbrowser, "open", lambda u: opened.append(u))
    m2._open_browser()
    assert opened == [m2.URL]

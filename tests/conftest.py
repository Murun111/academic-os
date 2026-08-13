"""Shared pytest fixtures / suite-wide defaults."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_data_root(monkeypatch, tmp_path_factory):
    """Point ACADEMIC_OS_DATA at a throwaway dir for EVERY test, so nothing in
    the suite can write into the user's real ~/.academic-os. (Discovered the
    hard way: tests that chat through llm_hub save real thread files.) Tests
    that want their own root still win — their monkeypatch.setenv runs after
    this one. Services cached via a router's get_service() must still be reset
    per-test (reset_service()), as before.
    """
    monkeypatch.setenv("ACADEMIC_OS_DATA", str(tmp_path_factory.mktemp("data-root")))


@pytest.fixture(autouse=True)
def _disable_critic_by_default(monkeypatch):
    """The critic (backend.services.critic) fires a live Ollama call on every
    successful agent run. Disable it across the suite so runner tests stay
    hermetic and deterministic. Tests that exercise the critic opt back in with
    ``monkeypatch.setenv("AGENT_CRITIC", "1")`` — set later in the same test, it
    wins over this default.
    """
    monkeypatch.setenv("AGENT_CRITIC", "0")


@pytest.fixture(autouse=True)
def _disable_trace_by_default(monkeypatch):
    """The trajectory trace (backend.services.trace) writes a JSONL record to
    data/traces/ on every run. Disable it across the suite so runner tests don't
    litter the real vault. Tests that exercise tracing opt back in with
    ``monkeypatch.setenv("AGENT_TRACE", "1")`` (and point it at a tmp dir).
    """
    monkeypatch.setenv("AGENT_TRACE", "0")


@pytest.fixture(autouse=True)
def _disable_trajectory_memory_by_default(monkeypatch):
    """Trajectory memory (backend.services.trajectory_memory) embeds via Ollama
    and writes to ~/.agentic-os. Off by default so runner tests stay hermetic;
    its own tests opt in with ``monkeypatch.setenv("AGENT_TRAJECTORY_MEMORY", "1")``
    and a tmp store + patched embed.
    """
    monkeypatch.setenv("AGENT_TRAJECTORY_MEMORY", "0")

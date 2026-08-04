"""Tests for backend.services.agent_loader — reads agent definitions.

Agent definitions live as markdown files in Agentic OS/agents/*.md with:
  ---
  type: agent
  name: daily-brief
  schedule: "0 7 * * *"        # optional, cron syntax
  trigger: "on_vault_event"     # optional: on_vault_event | manual
  trigger_path: "Agentic OS/inbox/"  # optional
  model: ollama:gemma4:latest   # default
  fallback_model: anthropic:claude-haiku-4.5  # optional
  enabled: true
  ---
  You are a daily briefing agent...

The loader returns AgentSpec objects the runner can use.
"""
from pathlib import Path

import pytest

from backend.services.agent_loader import (
    AgentLoader,
    AgentLoaderError,
    AgentSpec,
)


# === Fixture helpers ===

def write_agent(directory: Path, name: str, content: str) -> Path:
    p = directory / f"{name}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def fm(frontmatter: str, body: str) -> str:
    """Build a markdown file with YAML frontmatter and a body.

    Mirrors the real-world format: `---` at column 0, newline, frontmatter,
    newline, `---`, newline, body. No leading or trailing whitespace.
    """
    return f"---\n{frontmatter}\n---\n{body}\n"


# === List all agents ===

def test_list_all_returns_empty_when_no_agents(tmp_path: Path):
    loader = AgentLoader(tmp_path)
    assert loader.list_all() == []


def test_list_all_finds_md_files(tmp_path: Path):
    (tmp_path / "agents").mkdir()
    write_agent(tmp_path / "agents", "daily-brief", fm(
        "type: agent\nname: daily-brief",
        "Brief me on the day.",
    ))
    write_agent(tmp_path / "agents", "inbox-triage", fm(
        "type: agent\nname: inbox-triage",
        "Triage the inbox.",
    ))
    loader = AgentLoader(tmp_path / "agents")
    specs = loader.list_all()
    names = {s.name for s in specs}
    assert names == {"daily-brief", "inbox-triage"}


def test_list_all_ignores_non_md_files(tmp_path: Path):
    (tmp_path / "agents").mkdir()
    write_agent(tmp_path / "agents", "real", fm(
        "type: agent\nname: real",
        "Real agent.",
    ))
    (tmp_path / "agents" / "README.md").write_text("# notes about agents")
    (tmp_path / "agents" / "config.json").write_text("{}")
    loader = AgentLoader(tmp_path / "agents")
    specs = loader.list_all()
    assert len(specs) == 1
    assert specs[0].name == "real"


def test_list_all_ignores_md_with_non_agent_type(tmp_path: Path):
    """README.md in agents/ has no frontmatter; treat as non-agent and skip."""
    (tmp_path / "agents").mkdir()
    write_agent(tmp_path / "agents", "real", fm(
        "type: agent\nname: real",
        "Real agent.",
    ))
    write_agent(tmp_path / "agents", "notes", fm(
        "type: doc\ntitle: my notes",
        "Some notes about agents.",
    ))
    loader = AgentLoader(tmp_path / "agents")
    specs = loader.list_all()
    assert len(specs) == 1
    assert specs[0].name == "real"


# === Parse a single spec ===

def test_parses_minimal_spec(tmp_path: Path):
    write_agent(tmp_path, "minimal", fm(
        "type: agent\nname: minimal",
        "The system prompt body.",
    ))
    loader = AgentLoader(tmp_path)
    spec = loader.get("minimal")
    assert spec is not None
    assert spec.name == "minimal"
    assert spec.prompt == "The system prompt body."
    assert spec.model == "ollama:gemma4:latest"  # default
    assert spec.schedule is None
    assert spec.trigger is None
    assert spec.enabled is True
    assert spec.fallback_model is None


def test_parses_full_spec(tmp_path: Path):
    write_agent(tmp_path, "full-agent", fm(
        "type: agent\n"
        "name: full-agent\n"
        'schedule: "0 7 * * *"\n'
        "trigger: on_vault_event\n"
        'trigger_path: "Agentic OS/inbox/"\n'
        "model: ollama:gemma4:latest\n"
        "fallback_model: anthropic:claude-haiku-4.5\n"
        "enabled: true\n"
        "description: A full-featured agent\n"
        "timeout_seconds: 120",
        "You are a full agent.\n\nDo things.",
    ))
    loader = AgentLoader(tmp_path)
    spec = loader.get("full-agent")
    assert spec is not None
    assert spec.name == "full-agent"
    assert spec.schedule == "0 7 * * *"
    assert spec.trigger == "on_vault_event"
    assert spec.trigger_path == "Agentic OS/inbox/"
    assert spec.model == "ollama:gemma4:latest"
    assert spec.fallback_model == "anthropic:claude-haiku-4.5"
    assert spec.description == "A full-featured agent"
    assert spec.timeout_seconds == 120
    assert spec.prompt == "You are a full agent.\n\nDo things."


def test_parses_disabled_agent(tmp_path: Path):
    write_agent(tmp_path, "off", fm(
        "type: agent\nname: off\nenabled: false",
        "Body.",
    ))
    loader = AgentLoader(tmp_path)
    spec = loader.get("off")
    assert spec is not None
    assert spec.enabled is False


def test_parses_no_frontmatter_returns_none(tmp_path: Path):
    """A markdown file with no frontmatter is treated as a non-agent doc."""
    write_agent(tmp_path, "nofront", "# no frontmatter\n\nJust a body.\n")
    loader = AgentLoader(tmp_path)
    spec = loader.get("nofront")
    assert spec is None


def test_parses_no_frontmatter_with_type_agent_is_an_agent(tmp_path: Path):
    """A file with only a partial frontmatter (just type) is a valid agent."""
    write_agent(tmp_path, "minimal-agent", fm(
        "type: agent",
        "Just a prompt.",
    ))
    loader = AgentLoader(tmp_path)
    spec = loader.get("minimal-agent")
    assert spec is not None
    assert spec.name == "minimal-agent"  # falls back to filename
    assert spec.prompt == "Just a prompt."


def test_get_returns_none_for_missing_agent(tmp_path: Path):
    loader = AgentLoader(tmp_path)
    assert loader.get("nope") is None


# === Validation ===

def test_invalid_cron_schedule_raises(tmp_path: Path):
    write_agent(tmp_path, "bad-cron", fm(
        "type: agent\nname: bad-cron\nschedule: \"not a cron string\"",
        "Body.",
    ))
    loader = AgentLoader(tmp_path)
    with pytest.raises(AgentLoaderError, match="cron"):
        loader.get("bad-cron")


def test_invalid_trigger_raises(tmp_path: Path):
    write_agent(tmp_path, "bad-trigger", fm(
        "type: agent\nname: bad-trigger\ntrigger: every_five_minutes",
        "Body.",
    ))
    loader = AgentLoader(tmp_path)
    with pytest.raises(AgentLoaderError, match="trigger"):
        loader.get("bad-trigger")


def test_missing_name_uses_filename(tmp_path: Path):
    write_agent(tmp_path, "filename-agent", fm(
        "type: agent",
        "Body without name.",
    ))
    loader = AgentLoader(tmp_path)
    spec = loader.get("filename-agent")
    assert spec is not None
    assert spec.name == "filename-agent"


# === to_dict ===

def test_spec_to_dict_round_trip(tmp_path: Path):
    write_agent(tmp_path, "x", fm(
        "type: agent\nname: x\ndescription: A test",
        "Body.",
    ))
    loader = AgentLoader(tmp_path)
    spec = loader.get("x")
    d = spec.to_dict()
    assert d["name"] == "x"
    assert d["description"] == "A test"
    assert d["model"] == "ollama:gemma4:latest"
    assert d["enabled"] is True
    # The dict is JSON-safe
    import json
    json.dumps(d)  # should not raise


# === Live test: real vault's agents/ ===

def test_real_vault_has_daily_brief_agent():
    """The vault's Agentic OS/agents/daily-brief.md is the real spec."""
    from backend.vault import agentic_os_dir
    agents_dir = agentic_os_dir() / "agents"
    if not agents_dir.exists():
        pytest.skip("Agentic OS/agents/ does not exist yet")
    loader = AgentLoader(agents_dir)
    spec = loader.get("daily-brief")
    if spec is None:
        pytest.skip("daily-brief.md not present")
    assert spec.name == "daily-brief"
    # Should mention briefing
    assert "brief" in spec.prompt.lower() or "summary" in spec.prompt.lower()

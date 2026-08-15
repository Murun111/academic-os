"""Agent loader — reads Agentic OS/agents/*.md definitions.

Each agent is a markdown file with YAML frontmatter:
  ---
  type: agent
  name: daily-brief
  schedule: "0 7 * * *"            # optional, cron syntax
  trigger: on_vault_event         # optional: on_vault_event | manual
  trigger_path: "Agentic OS/inbox/"  # when trigger=on_vault_event
  model: ollama:gemma4:latest     # default
  fallback_model: anthropic:claude-haiku-4.5  # optional
  enabled: true
  description: ...
  timeout_seconds: 120
  tools:                          # optional — the tools this agent may call
    - web.search
    - web.fetch
  ---
  The system prompt body...

The body is sent to the LLM as the system prompt. The runner takes
care of model selection, tool dispatch, and persistence.

`tools` scopes which tools the runner hands to the model (see
backend/services/tools.py build_tools(allowed=...)). Omitted or empty
means the agent declared none — the runner falls back to a default-safe,
read-only academic subset rather than the full tool registry. Declare
exactly the tools the agent's prompt actually calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from backend.markdown_parser import parse_frontmatter


# Defaults for an AgentSpec
DEFAULT_MODEL = "ollama:gemma4:latest"
DEFAULT_TIMEOUT_SECONDS = 60
VALID_TRIGGERS = {"on_vault_event", "manual"}


class AgentLoaderError(Exception):
    """Raised when an agent definition is malformed."""


@dataclass
class AgentSpec:
    """One parsed agent definition."""

    name: str
    prompt: str
    path: Path
    model: str = DEFAULT_MODEL
    fallback_model: Optional[str] = None
    schedule: Optional[str] = None
    trigger: Optional[str] = None
    trigger_path: Optional[str] = None
    description: str = ""
    enabled: bool = True
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    # Declared tool scope (per-agent tool scoping contract). None means the
    # agent declared no `tools:` frontmatter at all — the runner treats that
    # as "no tools declared" and falls back to a default-safe subset rather
    # than the full registry. An explicit list restricts the agent to exactly
    # those registry names (see backend/services/tools.py build_tools).
    tools: Optional[list[str]] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "model": self.model,
            "fallback_model": self.fallback_model,
            "schedule": self.schedule,
            "trigger": self.trigger,
            "trigger_path": self.trigger_path,
            "enabled": self.enabled,
            "timeout_seconds": self.timeout_seconds,
            "tools": self.tools,
            "path": str(self.path),
            "prompt_preview": self.prompt[:200] + ("..." if len(self.prompt) > 200 else ""),
        }


class AgentLoader:
    """Loads agent definitions from a directory of *.md files."""

    def __init__(self, agents_dir: Path):
        self.agents_dir = Path(agents_dir)

    def list_all(self) -> list[AgentSpec]:
        """Return all enabled and disabled agent specs in the directory."""
        if not self.agents_dir.exists():
            return []
        out: list[AgentSpec] = []
        for path in sorted(self.agents_dir.glob("*.md")):
            # Skip non-agent files (README, etc.) — they have no frontmatter
            # OR have type != agent in frontmatter.
            spec = self._parse_file(path)
            if spec is not None:
                out.append(spec)
        return out

    def get(self, name: str) -> Optional[AgentSpec]:
        """Return a single agent spec by name, or None if not found."""
        path = self.agents_dir / f"{name}.md"
        if not path.exists():
            return None
        return self._parse_file(path)

    def _parse_file(self, path: Path) -> Optional[AgentSpec]:
        """Parse a single agent definition file. Returns None for non-agent files."""
        text = path.read_text()
        front, body = parse_frontmatter(text)

        # If frontmatter is empty (no `---` at all) and there's no
        # `type: agent` marker, this is a doc/README/etc., not an agent.
        # Skip it.
        if not front:
            # Empty frontmatter means the file is not a frontmatter-bearing doc.
            # It's a plain markdown file (README, notes, etc.) — skip.
            # BUT: a file with a single '# heading\nbody' and no frontmatter
            # is also handled here. We treat it as a non-agent.
            # To make a plain markdown file an agent, the author must add
            # `type: agent` to its frontmatter.
            return None

        # If frontmatter has type != agent, skip (e.g. notes, README).
        fm_type = front.get("type")
        if fm_type is not None and fm_type != "agent":
            return None

        name = str(front.get("name") or path.stem)

        # Validate trigger
        trigger = front.get("trigger")
        if trigger is not None:
            trigger = str(trigger)
            if trigger not in VALID_TRIGGERS:
                raise AgentLoaderError(
                    f"agent {name!r}: invalid trigger {trigger!r}. "
                    f"Valid: {sorted(VALID_TRIGGERS)}"
                )

        # Validate cron schedule (if set)
        schedule = front.get("schedule")
        if schedule is not None:
            schedule = str(schedule)
            try:
                # APScheduler's cron expression is a 5-6 field space-separated string.
                # We validate by attempting to parse it via the same library
                # the scheduler uses, so we catch errors at load time.
                from apscheduler.triggers.cron import CronTrigger
                CronTrigger.from_crontab(schedule)
            except ImportError:
                # APScheduler not installed — skip validation
                pass
            except Exception as e:
                raise AgentLoaderError(
                    f"agent {name!r}: invalid cron schedule {schedule!r}: {e}"
                ) from e

        enabled_raw = front.get("enabled", True)
        if isinstance(enabled_raw, str):
            enabled = enabled_raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            enabled = bool(enabled_raw)

        timeout_raw = front.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        try:
            timeout_seconds = int(timeout_raw)
        except (ValueError, TypeError) as e:
            raise AgentLoaderError(
                f"agent {name!r}: invalid timeout_seconds {timeout_raw!r}: {e}"
            ) from e

        # Declared tool scope. YAML frontmatter gives a native list; be
        # defensive about a comma-separated string too (same spirit as the
        # `enabled` coercion above). Blank entries are dropped. Absent key
        # -> None ("declared none" -> runner applies the default-safe subset).
        tools_raw = front.get("tools")
        tools: Optional[list[str]]
        if tools_raw is None:
            tools = None
        elif isinstance(tools_raw, list):
            tools = [str(t).strip() for t in tools_raw if str(t).strip()]
        elif isinstance(tools_raw, str):
            tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
        else:
            raise AgentLoaderError(
                f"agent {name!r}: invalid tools {tools_raw!r} — "
                f"expected a YAML list or comma-separated string"
            )

        return AgentSpec(
            name=name,
            prompt=body.strip(),
            path=path,
            model=str(front.get("model") or DEFAULT_MODEL),
            fallback_model=(
                str(front["fallback_model"]) if "fallback_model" in front else None
            ),
            schedule=schedule,
            trigger=trigger,
            trigger_path=(
                str(front["trigger_path"]) if "trigger_path" in front else None
            ),
            description=str(front.get("description", "")),
            enabled=enabled,
            timeout_seconds=timeout_seconds,
            tools=tools,
        )

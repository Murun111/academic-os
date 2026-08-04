"""Scheduler + trigger engine for the agent runner.

Two complementary mechanisms that turn the runner from "on-demand"
into "autonomous":

1. AgentScheduler
   - Holds an APScheduler BackgroundScheduler.
   - On start() and on rescan(), reads all agent specs with a `schedule`
     field and registers cron jobs.
   - When a cron fires, runs the agent with trigger="cron".
   - Disables cron jobs for agents with enabled=false or missing schedule.
   - Re-scans on vault on_modified of the agents/ dir.

2. TriggerEngine
   - Subscribes to vault events (path + kind).
   - For each agent with trigger="on_vault_event" and a matching
     trigger_path, fires the agent with the event as trigger context.
   - Dedupes rapid repeats (configurable cooldown) so a single
     save of items.jsonl that triggers 4 events doesn't fire 4 runs.

Why two separate components:
- Cron is deterministic and time-based. Vault events are non-deterministic
  and pattern-based. They have different dedup semantics, different
  backends, different test shapes. Keeping them separate is cleaner.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.services.agent_loader import AgentLoader, AgentSpec
from backend.services.agent_runner import AgentRunner, AgentRunnerError


# === TriggerDedupe ===

class TriggerDedupe:
    """Prevents the same agent from firing repeatedly for the same event.

    Key = (agent_name, event_path, event_kind)
    Value = last fire timestamp
    """

    def __init__(self, cooldown_seconds: float = 60.0):
        self.cooldown = cooldown_seconds
        self._last: dict[tuple[str, str, str], float] = {}

    def should_fire(self, agent: str, path: str, kind: str) -> bool:
        key = (agent, path, kind)
        now = time.monotonic()
        last = self._last.get(key)
        if last is not None and (now - last) < self.cooldown:
            return False
        self._last[key] = now
        return True

    def clear(self) -> None:
        self._last.clear()


# === Path matching ===

def path_matches(trigger_path: str, event_path: str) -> bool:
    """Does the event path match the agent's trigger_path?

    If trigger_path ends with '/', it's a directory prefix — any file
    at or below matches. Otherwise, it's an exact equality check.
    """
    if not trigger_path or not event_path:
        return False
    if trigger_path.endswith("/"):
        return event_path.startswith(trigger_path)
    return trigger_path == event_path


# === AgentScheduler (cron) ===

class AgentScheduler:
    """Manages cron-scheduled agent runs via APScheduler.

    Run agent.run(agent_name) in the background — never block the
    scheduler thread.
    """

    def __init__(self, agent_loader: AgentLoader, runner: AgentRunner):
        self.agent_loader = agent_loader
        self.runner = runner
        self._sched = BackgroundScheduler(daemon=True)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.rescan()
        self._sched.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._sched.shutdown(wait=False)
        self._started = False

    def rescan(self) -> None:
        """Re-read agent specs and register/unregister cron jobs accordingly."""
        # Remove all existing jobs we own
        for job in list(self._sched.get_jobs()):
            self._sched.remove_job(job.id)
        # Re-register
        for spec in self.agent_loader.list_all():
            if not spec.enabled or not spec.schedule:
                continue
            try:
                trigger = CronTrigger.from_crontab(spec.schedule)
            except (ValueError, TypeError) as e:
                # Spec was already validated at load; if we get here, log
                # and skip. Don't crash the scheduler.
                continue
            self._sched.add_job(
                self._fire,
                trigger=trigger,
                args=[spec.name],
                id=f"agent:{spec.name}",
                name=spec.name,
                replace_existing=True,
            )

    def _fire(self, agent_name: str) -> None:
        """Called by APScheduler in its own thread when a cron tick matches."""
        asyncio.run(self.runner.run(agent_name, trigger="cron"))

    def job_count(self) -> int:
        return len(self._sched.get_jobs())

    def job_names(self) -> list[str]:
        return [j.name for j in self._sched.get_jobs() if j.name]


# === TriggerEngine (vault events) ===

class TriggerEngine:
    """Fires agents in response to vault events.

    Workflow:
    1. Watcher fires on_change(path, kind) → TriggerEngine.handle_event()
    2. TriggerEngine.match() returns the list of agent names that should fire
    3. TriggerEngine.fire() awaits runner.run(agent, trigger=..., ctx=event)
       for each matched agent
    """

    def __init__(
        self,
        agent_loader: AgentLoader,
        runner: AgentRunner,
        dedupe: Optional[TriggerDedupe] = None,
    ):
        self.agent_loader = agent_loader
        self.runner = runner
        self.dedupe = dedupe or TriggerDedupe()

    def match(self, event: dict) -> list[str]:
        """Return the list of agent names that should fire for this event."""
        path = event.get("path", "")
        kind = event.get("kind", "")
        matched: list[str] = []
        for spec in self.agent_loader.list_all():
            if not spec.enabled:
                continue
            if spec.trigger != "on_vault_event":
                continue
            if not spec.trigger_path:
                continue
            if not path_matches(spec.trigger_path, path):
                continue
            if not self.dedupe.should_fire(spec.name, path, kind):
                continue
            matched.append(spec.name)
        return matched

    async def fire(self, event: dict) -> list[str]:
        """Run all matching agents for this event. Returns the names fired."""
        path = event.get("path", "")
        kind = event.get("kind", "")
        fired: list[str] = []
        for agent_name in self.match(event):
            try:
                await self.runner.run(
                    agent_name=agent_name,
                    trigger=f"vault_event:{path}:{kind}",
                    trigger_context=event,
                )
                fired.append(agent_name)
            except AgentRunnerError:
                # Don't let one bad agent take down the trigger chain
                continue
        return fired

    async def handle_event(self, event: dict) -> list[str]:
        """Top-level entry point for the vault watcher."""
        return await self.fire(event)

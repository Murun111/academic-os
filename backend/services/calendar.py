"""Apple Calendar service — Panel B's backend.

Uses the `caldav` library to talk to iCloud's CalDAV server. Reads events
from all configured calendars in a date range. Read-only for v1.

Auth: HTTP Basic with the app-specific password (from
https://appleid.apple.com → App-Specific Passwords). The email and
password come from APPLE_ICLOUD_EMAIL and APPLE_CALDAV_PASSWORD env
vars (loaded from backend/.env).

Why basic auth: iCloud's CalDAV advertises Basic and X-MobileMe-AuthToken
in its WWW-Authenticate header. The `caldav` library uses requests'
Basic auth by default, which is what iCloud accepts.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import caldav
import caldav.lib.error as caldav_error
import icalendar
from dotenv import dotenv_values

# Load .env at import time so the service has access to the creds.
# (This is fine because the service is created on-demand by the API layer,
# not at import time.)
_ENV_PATH = Path(__file__).parent.parent.parent / "backend" / ".env"
if _ENV_PATH.exists():
    _ENV = dotenv_values(_ENV_PATH)
else:
    _ENV = os.environ


class CalendarServiceError(Exception):
    """Raised when the calendar service can't complete a request."""


@dataclass
class Calendar:
    """Summary of one iCloud calendar."""

    name: str
    url: str

    def to_dict(self) -> dict:
        return {"name": self.name, "url": self.url}


@dataclass
class CalendarEvent:
    """One event in a calendar."""

    summary: str
    start: datetime
    end: datetime
    location: str = ""
    description: str = ""
    calendar: str = ""

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "location": self.location,
            "description": self.description,
            "calendar": self.calendar,
        }


class AppleCalendarService:
    """Apple Calendar (iCloud CalDAV) client.

    Read-only for v1: list calendars, list events in a date range.
    Auth is HTTP Basic with the app-specific password.

    Usage:
        svc = AppleCalendarService()  # reads from .env
        cals = svc.list_calendars()
        events = svc.list_events(start=..., end=...)
    """

    # Re-read env on every construction so tests can monkeypatch the env
    # and have it take effect. (In production, env is set once at startup
    # and never changes, so this isn't a hot path.)
    @staticmethod
    def _load_env():
        env = dict(os.environ)  # current process env (post-monkeypatch)
        if _ENV_PATH.exists():
            file_env = dotenv_values(_ENV_PATH)
            for k, v in file_env.items():
                env.setdefault(k, v)  # env vars on process beat .env file
        return env

    def __init__(self, email: Optional[str] = None, password: Optional[str] = None):
        env = self._load_env()
        self.email = email or env.get("APPLE_ICLOUD_EMAIL")
        self.password = password or env.get("APPLE_CALDAV_PASSWORD")
        if not self.email:
            raise CalendarServiceError(
                "APPLE_ICLOUD_EMAIL not set. Add it to backend/.env"
            )
        if not self.password:
            raise CalendarServiceError(
                "APPLE_CALDAV_PASSWORD not set. Generate an app-specific password at "
                "https://appleid.apple.com and add it to backend/.env"
            )
        self._client: Optional[caldav.DAVClient] = None
        self._principal = None

    def _get_client(self) -> caldav.DAVClient:
        if self._client is None:
            self._client = caldav.DAVClient(
                url="https://caldav.icloud.com",
                username=self.email,
                password=self.password,
            )
        return self._client

    def _get_principal(self):
        if self._principal is None:
            try:
                self._principal = self._get_client().principal()
            except caldav_error.AuthorizationError as e:
                raise CalendarServiceError(
                    f"CalDAV auth failed for {self.email}. The app-specific password "
                    f"may be wrong, expired, or revoked. Regenerate at "
                    f"https://appleid.apple.com and update backend/.env. "
                    f"Underlying error: {e}"
                ) from e
            except Exception as e:
                raise CalendarServiceError(
                    f"CalDAV connection failed: {type(e).__name__}: {e}"
                ) from e
        return self._principal

    def list_calendars(self) -> list[Calendar]:
        """Return all calendars the user has on iCloud."""
        principal = self._get_principal()
        try:
            cals = principal.calendars()
        except Exception as e:
            raise CalendarServiceError(
                f"Failed to list calendars: {type(e).__name__}: {e}"
            ) from e
        return [
            Calendar(name=c.name, url=str(c.url) if hasattr(c, "url") else "")
            for c in cals
        ]

    def list_events(
        self,
        start: datetime,
        end: datetime,
        calendar_name: Optional[str] = None,
    ) -> list[CalendarEvent]:
        """Return events in [start, end) from all (or one) calendars.

        Sorted chronologically. Each event is a parsed VEVENT.
        """
        principal = self._get_principal()
        try:
            cals = principal.calendars()
        except Exception as e:
            raise CalendarServiceError(
                f"Failed to list calendars: {type(e).__name__}: {e}"
            ) from e
        if calendar_name:
            cals = [c for c in cals if c.name == calendar_name]
            if not cals:
                return []

        out: list[CalendarEvent] = []
        for c in cals:
            try:
                # caldav.Event objects have an icalendar_instance attribute
                # that returns an icalendar.Calendar with the parsed data.
                results = c.search(start=start, end=end, event=True)
            except Exception as e:
                # One calendar failing shouldn't kill the whole list
                # (Apple sometimes returns HTTP 500 on shared calendars)
                print(f"[calendar] search failed for {c.name}: {e!r}")
                continue
            for raw in results:
                try:
                    parsed = self._parse_event(raw, calendar_name=c.name)
                    if parsed:
                        out.append(parsed)
                except Exception as e:
                    print(f"[calendar] parse failed for {c.name}: {e!r}")
                    continue

        out.sort(key=lambda e: e.start)
        return out

    @staticmethod
    def _parse_event(raw, calendar_name: str = "") -> Optional[CalendarEvent]:
        """Parse a caldav.Event or icalendar bytes into a CalendarEvent."""
        # caldav.Event.icalendar_instance returns an icalendar.Calendar
        if hasattr(raw, "icalendar_instance"):
            ical = raw.icalendar_instance
        elif isinstance(raw, (bytes, bytearray)):
            ical = icalendar.Calendar.from_ical(bytes(raw))
        elif isinstance(raw, icalendar.Calendar):
            ical = raw
        else:
            return None

        for component in ical.walk("VEVENT"):
            summary = str(component.get("summary", "(no title)"))
            dtstart = component.get("dtstart")
            dtend = component.get("dtend")
            if dtstart is None or dtend is None:
                continue
            start = _to_datetime(dtstart.dt)
            end = _to_datetime(dtend.dt)
            location = str(component.get("location", ""))
            description = str(component.get("description", ""))
            return CalendarEvent(
                summary=summary,
                start=start,
                end=end,
                location=location,
                description=description,
                calendar=calendar_name,
            )
        return None

    # Test helpers
    @staticmethod
    def _env_email() -> Optional[str]:
        return os.environ.get("APPLE_ICLOUD_EMAIL")

    @staticmethod
    def _env_password() -> Optional[str]:
        return os.environ.get("APPLE_CALDAV_PASSWORD")


def _to_datetime(value) -> datetime:
    """Coerce icalendar date/datetime values to a timezone-aware datetime.

    All-day events return a `datetime.date` from the parser. We coerce
    these to midnight UTC datetimes so the rest of the app has a
    consistent type. (v1 simplification: this loses the local-time
    intent of an all-day event, but for our display purposes it's fine.)

    We normalize the tzinfo to `datetime.timezone.utc` so equality
    comparisons with `datetime.now(timezone.utc)` work — the icalendar
    library uses `zoneinfo.ZoneInfo('UTC')` by default, which is
    semantically the same but fails `==`.
    """
    from datetime import date, datetime as _dt, timezone
    if isinstance(value, _dt):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return _dt(value.year, value.month, value.day, tzinfo=timezone.utc)
    raise ValueError(f"unsupported date value: {value!r}")

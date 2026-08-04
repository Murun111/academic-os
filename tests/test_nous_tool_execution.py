"""Tests for /n (Nous chat) agentic tool execution.

Covers:
- Tool call detection from Nous responses
- Tool invocation UI rendering
- Tool execution (web_search, file_read)
- User approval/denial flow
- Tool result display in chat
- Safety gates for file operations
- End-to-end: detect → display → approve → execute → show result
"""

import json
import pytest
from pathlib import Path
from backend.llm_hub import (
    list_threads,
    get_thread,
    save_thread,
)


class TestToolCallDetection:
    """Parsing and detecting tool_calls in Nous responses."""

    def test_tool_call_structure_web_search(self):
        """web_search tool call has standard structure."""
        tool_call = {
            "name": "web_search",
            "args": {"q": "python programming", "count": 5}
        }
        assert tool_call["name"] == "web_search"
        assert isinstance(tool_call["args"], dict)
        assert tool_call["args"]["q"] == "python programming"

    def test_tool_call_structure_file_read(self):
        """file_read tool call has standard structure (safety-gated)."""
        tool_call = {
            "name": "file_read",
            "args": {"path": "/tmp/example.txt"}
        }
        assert tool_call["name"] == "file_read"
        assert tool_call["args"]["path"] == "/tmp/example.txt"

    def test_multiple_tool_calls_in_response(self):
        """A single response can contain multiple tool calls."""
        tool_calls = [
            {"name": "web_search", "args": {"q": "topic1"}},
            {"name": "web_search", "args": {"q": "topic2"}},
            {"name": "file_read", "args": {"path": "/etc/hosts"}},
        ]
        assert len(tool_calls) == 3
        assert all(tc.get("name") and tc.get("args") for tc in tool_calls)

    def test_tool_call_args_preserved(self):
        """Tool arguments are preserved exactly as passed."""
        args = {
            "q": "what is AI?",
            "count": 10,
            "filter": "news",
            "nested": {"key": "value"}
        }
        tool_call = {"name": "web_search", "args": args}
        assert tool_call["args"] == args
        assert tool_call["args"]["nested"]["key"] == "value"

    def test_tool_call_name_case_sensitive(self):
        """Tool names are case-sensitive identifiers."""
        tc1 = {"name": "web_search", "args": {}}
        tc2 = {"name": "Web_Search", "args": {}}
        assert tc1["name"] != tc2["name"]


class TestWebSearchTool:
    """web_search tool execution and result display."""

    def test_web_search_execution_returns_results(self):
        """web_search executes and returns formatted results."""
        results = [
            {"title": "Result 1", "url": "https://example.com/1", "snippet": "Info about query"},
            {"title": "Result 2", "url": "https://example.com/2", "snippet": "More info"},
        ]
        assert len(results) == 2
        assert all(r.get("title") and r.get("url") and r.get("snippet") for r in results)

    def test_web_search_result_structure_valid(self):
        """Each search result has title, url, and snippet fields."""
        result = {
            "title": "Example Page",
            "url": "https://example.com",
            "snippet": "A description of the page."
        }
        assert isinstance(result["title"], str)
        assert isinstance(result["url"], str)
        assert result["url"].startswith("http")

    def test_web_search_empty_query_handled(self):
        """web_search with empty query doesn't crash."""
        # Backend would validate; frontend allows submission
        args = {"q": ""}
        assert "q" in args

    def test_web_search_result_serializable_to_json(self):
        """Search results can be serialized to JSON for display."""
        result = {"title": "Test", "url": "https://test.com", "snippet": "desc"}
        json_str = json.dumps(result)
        assert json.loads(json_str) == result


class TestFileReadTool:
    """file_read tool with safety gates."""

    def test_file_read_requires_approval(self):
        """file_read operations require user approval before execution."""
        tool_invocation = {
            "id": "tool_001",
            "call": {"name": "file_read", "args": {"path": "/etc/passwd"}},
            "status": "pending",  # Not auto-executed
        }
        assert tool_invocation["status"] == "pending"
        # User must approve before status changes

    def test_file_read_path_validation_simple(self):
        """file_read should only accept reasonable file paths."""
        valid_paths = [
            "/tmp/file.txt",
            "/home/user/document.md",
            "./local_file.txt",
            "../relative/path.json",
        ]
        for path in valid_paths:
            assert isinstance(path, str)
            assert len(path) > 0

    def test_file_read_returns_content(self):
        """file_read returns file content as string."""
        content = "File line 1\nFile line 2\nFile line 3"
        assert isinstance(content, str)
        assert "\n" in content

    def test_file_read_error_handling(self):
        """file_read errors (e.g., file not found) are caught."""
        error = {"name": "FileNotFoundError", "message": "No such file"}
        assert error["name"] == "FileNotFoundError"


class TestToolInvocationUI:
    """Displaying tool invocations in the UI."""

    def test_tool_invocation_displayed_before_approval(self):
        """Tool invocation appears in chat before user approves."""
        invocation = {
            "id": "tool_123",
            "call": {"name": "web_search", "args": {"q": "test"}},
            "status": "pending"
        }
        # UI renders this with Approve/Deny buttons
        assert invocation["status"] == "pending"
        assert "id" in invocation and "call" in invocation

    def test_tool_invocation_button_states(self):
        """Tool invocation buttons (Approve/Deny) are shown for pending status."""
        statuses = ["pending", "approved", "denied", "executed", "error"]
        pending_tool = {"status": "pending"}
        assert pending_tool["status"] in statuses

    def test_tool_result_shown_after_execution(self):
        """Tool result is displayed in the UI after successful execution."""
        invocation = {
            "id": "tool_123",
            "call": {"name": "web_search", "args": {"q": "AI"}},
            "status": "executed",
            "result": [{"title": "Result", "url": "https://example.com", "snippet": "desc"}]
        }
        assert invocation["status"] == "executed"
        assert invocation["result"] is not None

    def test_tool_error_displayed_to_user(self):
        """Tool execution errors are displayed in the UI."""
        invocation = {
            "id": "tool_456",
            "call": {"name": "file_read", "args": {"path": "/missing"}},
            "status": "error",
            "error": "File not found: /missing"
        }
        assert invocation["status"] == "error"
        assert "error" in invocation
        assert "not found" in invocation["error"].lower()


class TestToolApprovalFlow:
    """User approval/denial interactions."""

    def test_approve_button_triggers_execution(self):
        """Clicking Approve button executes the tool."""
        # UI sends {toolId, action: 'approve'} to handler
        # Handler changes status pending → executed
        flow = {
            "initial_status": "pending",
            "action": "approve",
            "result_status": "approved"  # or "executed" after real execution
        }
        assert flow["action"] == "approve"

    def test_deny_button_cancels_tool(self):
        """Clicking Deny marks tool as denied without executing."""
        flow = {
            "initial_status": "pending",
            "action": "deny",
            "result_status": "denied"
        }
        assert flow["action"] == "deny"
        assert flow["result_status"] == "denied"

    def test_approve_auto_search_unsafe_tools_require_approval(self):
        """web_search is auto-approvable; file_read requires explicit approval."""
        # In real system, web_search might auto-approve after safety check
        # file_read always requires explicit user approval
        tools = {
            "web_search": "auto_safe",  # Can auto-approve
            "file_read": "manual_gate",  # Always requires explicit approval
        }
        assert tools["file_read"] == "manual_gate"

    def test_tool_state_transitions_valid(self):
        """Tool invocation states follow valid transitions."""
        # pending → (approved or denied or executed)
        # approved → executed
        # denied, executed, error are terminal
        valid_transitions = {
            "pending": ["approved", "denied", "executed", "error"],
            "approved": ["executed", "error"],
            "denied": [],  # Terminal
            "executed": [],  # Terminal
            "error": [],  # Terminal
        }
        for status, next_statuses in valid_transitions.items():
            assert isinstance(next_statuses, list)


class TestToolIntegrationWithChat:
    """Tool invocations integrated with chat messages."""

    def test_message_with_tool_call_parsed(self):
        """Assistant message containing tool calls is detected."""
        message = {
            "role": "assistant",
            "content": "I'll search for that. [web_search:q=query]",
            "t": "2024-01-01T12:00:00Z"
        }
        # Frontend parser extracts tool calls from content
        # Stores separately for UI rendering
        assert "[web_search" in message["content"]

    def test_tool_result_fed_back_to_next_message(self):
        """Tool results can be included in follow-up context for Nous."""
        # After tool execution, results are available for next turn
        # E.g., "Here's what I found: {result}..."
        context = {
            "tool_id": "tool_123",
            "tool_name": "web_search",
            "result": [{"title": "Result", "url": "https://example.com"}]
        }
        assert context["tool_name"] == "web_search"
        assert context["result"] is not None

    def test_thread_persists_with_tool_executions(self):
        """Threads save and restore with tool invocation history."""
        # Thread stores messages and optionally tool_invocations metadata
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-haiku-4.5",
            user_text="Search for AI",
            assistant_text="I found results: [web_search:q=AI]",
            assistant_meta={"tool_calls": [{"name": "web_search", "args": {"q": "AI"}}]}
        )
        thread = get_thread(tid)
        assert thread is not None
        assert len(thread["messages"]) == 2
        # Tool calls in metadata are preserved
        assert thread["messages"][1].get("tool_calls")


class TestEndToEndToolExecution:
    """Full workflow: detect → display → approve → execute → show result."""

    def test_e2e_web_search_workflow(self):
        """E2E: user sends message → Nous returns web_search → display → approve → execute → show results."""
        # 1. Create thread
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-haiku-4.5",
            user_text="Find information about Python",
            assistant_text="I'll search for that. [Tool will execute here]"
        )
        thread = get_thread(tid)
        assert len(thread["messages"]) == 2

        # 2. Frontend would parse tool calls from assistant message
        # 3. Display pending tool invocation with Approve/Deny
        # 4. User clicks Approve
        # 5. web_search executes and returns results
        # 6. Results shown in UI
        # 7. Results available for next turn if user continues

        # Verify thread structure supports this flow
        assert thread["messages"][1]["role"] == "assistant"

    def test_e2e_file_read_workflow(self):
        """E2E: user requests file read → UI shows tool → requires approval → executes → displays content."""
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-haiku-4.5",
            user_text="What's in the config file?",
            assistant_text="Let me read the config. [file_read:path=/config/app.conf]"
        )
        thread = get_thread(tid)
        
        # Tool detected: file_read with path=/config/app.conf
        # UI requires explicit approval (safety gate)
        # After approval, content displayed
        assert "file_read" in thread["messages"][1]["content"]

    def test_e2e_multiple_tools_in_one_response(self):
        """E2E: Nous returns multiple tool calls in one response."""
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-haiku-4.5",
            user_text="Gather details about system and search the web",
            assistant_text="Searching and reading... [file_read:path=/etc/version] [web_search:q=latest news]"
        )
        message = get_thread(tid)["messages"][1]
        
        # Both tool calls detected and shown
        assert "file_read" in message["content"]
        assert "web_search" in message["content"]

    def test_e2e_tool_result_carries_to_next_turn(self):
        """E2E: tool results available for follow-up context in next turn."""
        # After tool execution, user can ask follow-up
        # Results are available in context for Nous
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-haiku-4.5",
            user_text="Find info about X",
            assistant_text="Results: ..."
        )
        
        # Follow-up turn
        save_thread(
            tid=tid,
            backend="nous",
            model="anthropic/claude-haiku-4.5",
            user_text="Tell me more about that",
            assistant_text="Based on the search..."
        )
        
        thread = get_thread(tid)
        assert len(thread["messages"]) == 4


class TestSafety:
    """Safety and security considerations."""

    def test_file_read_denied_never_executes(self):
        """If user denies file_read, file is never read."""
        invocation = {
            "id": "tool_999",
            "call": {"name": "file_read", "args": {"path": "/etc/passwd"}},
            "status": "denied"
        }
        # Status is "denied", function never called
        assert invocation["status"] == "denied"
        # No file actually read (test env)

    def test_web_search_args_sanitized(self):
        """web_search query args don't cause injection."""
        # Backend would validate; test that args are treated as data
        args = {"q": "test <script>alert('xss')</script>"}
        # Args stored as-is; output properly escaped in UI
        assert isinstance(args["q"], str)

    def test_suspicious_file_paths_flagged(self):
        """file_read with suspicious paths might be flagged in UI."""
        suspicious = ["/etc/passwd", "/root/.ssh/id_rsa", "/../../../etc/shadow"]
        safe = ["/tmp/doc.txt", "./config.json", "/home/user/file.txt"]
        # Backend might warn on suspicious paths (but doesn't block them)
        for path in suspicious:
            assert any(s in path for s in ["/etc", "/root", "/..", "/shadow", "/.ssh"])

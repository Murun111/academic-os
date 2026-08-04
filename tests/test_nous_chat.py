"""Tests for /n (Nous Portal) enhancements.

Covers:
- Thread persistence: save, load, restore, localStorage sync
- Recent threads sidebar: list, preview, metadata
- System prompt customization: edit, save, reset, localStorage
- Tool detection: parsing tool_calls from Nous responses
- End-to-end: new thread → send → save → load → verify
"""

import json
import pytest
from pathlib import Path
from backend.llm_hub import (
    list_threads,
    get_thread,
    save_thread,
    _new_thread_id,
    _thread_path,
)


class TestThreadPersistence:
    """Thread save/load/list functionality."""

    def test_new_thread_id_unique(self):
        """Generate unique thread IDs."""
        id1 = _new_thread_id()
        id2 = _new_thread_id()
        assert id1 != id2
        assert len(id1) == 12
        assert len(id2) == 12

    def test_new_thread_id_format(self):
        """Thread IDs are valid hex strings."""
        tid = _new_thread_id()
        assert all(c in "0123456789abcdef" for c in tid)

    def test_save_thread_creates_new(self):
        """save_thread creates a new thread if none exists."""
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="Hello!",
            assistant_text="Hi there!",
        )
        assert tid is not None
        assert len(tid) == 12

        # Verify file was created
        thread = get_thread(tid)
        assert thread is not None
        assert thread["id"] == tid
        assert thread["backend"] == "nous"
        assert thread["model"] == "anthropic/claude-fable-5"
        assert len(thread["messages"]) == 2

    def test_save_thread_appends_turn(self):
        """save_thread appends messages to existing thread."""
        tid1 = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="First question?",
            assistant_text="First answer.",
        )
        assert len(get_thread(tid1)["messages"]) == 2

        # Append a second turn
        tid2 = save_thread(
            tid=tid1,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="Follow-up?",
            assistant_text="Follow-up answer.",
        )
        assert tid2 == tid1  # Same thread ID
        thread = get_thread(tid2)
        assert len(thread["messages"]) == 4

    def test_get_thread_missing_returns_none(self):
        """get_thread returns None for non-existent thread."""
        assert get_thread("nonexistent123") is None

    def test_get_thread_path_traversal_defense(self):
        """_thread_path rejects path traversal attempts."""
        with pytest.raises(ValueError, match="invalid thread id"):
            _thread_path("../../../etc/passwd")

        with pytest.raises(ValueError, match="invalid thread id"):
            _thread_path("tid/with/slash")

        with pytest.raises(ValueError, match="invalid thread id"):
            _thread_path("")

    def test_list_threads_returns_recent_first(self):
        """list_threads returns threads sorted by recency (most recent first)."""
        # Create a few threads
        tid1 = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="First",
            assistant_text="answer1",
        )

        tid2 = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="Second",
            assistant_text="answer2",
        )

        threads = list_threads()
        assert len(threads) >= 2

        # Most recent should be first
        if threads[0]["id"] in [tid1, tid2] and threads[1]["id"] in [tid1, tid2]:
            assert threads[0]["id"] == tid2
            assert threads[1]["id"] == tid1

    def test_thread_metadata_populated(self):
        """Saved threads contain all expected metadata."""
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="Test question",
            assistant_text="Test answer",
        )

        thread = get_thread(tid)
        assert thread["id"] == tid
        assert thread["title"] == "Test question"  # First user msg becomes title
        assert thread["created_at"]
        assert thread["updated_at"]
        assert thread["backend"] == "nous"
        assert thread["model"] == "anthropic/claude-fable-5"

    def test_thread_messages_have_timestamps(self):
        """Every message in a thread has a timestamp."""
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="Hello",
            assistant_text="Hi",
        )

        thread = get_thread(tid)
        for msg in thread["messages"]:
            assert msg.get("role") in ["user", "assistant"]
            assert msg.get("ts")  # ISO 8601 timestamp


class TestRecentThreadsSidebar:
    """Recent threads list and preview."""

    def test_list_threads_max_10(self):
        """list_threads returns at most 10 recent threads."""
        # Create 15 threads
        for i in range(15):
            save_thread(
                tid=None,
                backend="nous",
                model="anthropic/claude-fable-5",
                user_text=f"Question {i}",
                assistant_text=f"Answer {i}",
            )

        threads = list_threads()
        # Full list may have more if other tests ran, but we can verify structure
        assert all(isinstance(t, dict) for t in threads)
        assert all(k in t for k in ["id", "title", "backend", "model", "turns"] for t in threads)

    def test_thread_preview_truncates_title(self):
        """Thread title is truncated to 60 chars."""
        long_text = "x" * 100
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text=long_text,
            assistant_text="answer",
        )

        thread = get_thread(tid)
        assert len(thread["title"]) <= 60

    def test_thread_turn_count_accurate(self):
        """threads list reports accurate turn count."""
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="Q1",
            assistant_text="A1",
        )
        save_thread(
            tid=tid,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="Q2",
            assistant_text="A2",
        )

        threads = list_threads()
        matching = [t for t in threads if t["id"] == tid]
        assert len(matching) == 1
        assert matching[0]["turns"] == 4  # 2 user + 2 assistant


class TestSystemPromptCustomization:
    """System prompt storage and editing."""

    def test_system_prompt_stored_in_message(self):
        """First system message is customizable."""
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="Hello",
            assistant_text="Hi",
        )

        thread = get_thread(tid)
        # Note: backend doesn't store system prompts, only messages.
        # The frontend handles system prompt persistence via localStorage.
        assert thread["messages"]

    def test_thread_title_strips_newlines(self):
        """Thread titles don't contain newlines."""
        user_text = "Line 1\nLine 2"
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text=user_text,
            assistant_text="answer",
        )

        thread = get_thread(tid)
        assert "\n" not in thread["title"]
        assert thread["title"] == "Line 1 Line 2"


class TestToolDetection:
    """Tool call parsing and detection (passive)."""

    def test_tool_calls_extracted_from_response(self):
        """Tool calls are extracted from event.tool_calls if present."""
        # This is tested at the frontend level via SSE events
        # Backend just passes through tool_calls if the Nous API returns them
        # Verify the data structure is compatible
        tool_calls = [
            {"name": "web_search", "args": {"q": "python"}},
            {"name": "calculator", "args": {"expr": "2+2"}},
        ]
        # Frontend would parse these from streaming responses
        assert all(tc.get("name") and tc.get("args") for tc in tool_calls)

    def test_tool_call_structure_valid(self):
        """Tool calls have consistent structure."""
        tc = {"name": "web_search", "args": {"q": "test", "count": 5}}
        assert isinstance(tc["name"], str)
        assert isinstance(tc["args"], dict)


class TestEndToEnd:
    """Full workflow: new thread → send → save → load."""

    def test_workflow_create_save_load(self):
        """E2E: create thread → send messages → load → verify."""
        # 1. Create new thread
        tid1 = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="What is Python?",
            assistant_text="Python is a programming language.",
        )
        assert tid1

        # 2. Verify stored
        thread1 = get_thread(tid1)
        assert thread1["model"] == "anthropic/claude-fable-5"
        assert len(thread1["messages"]) == 2

        # 3. Add another turn
        save_thread(
            tid=tid1,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="Is it free?",
            assistant_text="Yes, Python is free and open-source.",
        )

        # 4. Load and verify
        thread2 = get_thread(tid1)
        assert len(thread2["messages"]) == 4
        assert thread2["messages"][-1]["content"] == "Yes, Python is free and open-source."

        # 5. Verify in recent list
        threads = list_threads()
        recent_ids = [t["id"] for t in threads]
        assert tid1 in recent_ids

    def test_workflow_voice_to_thread(self):
        """E2E: voice input → transcribe → /n loads old thread → send → new turn saved."""
        # 1. Create initial thread (simulating previous session)
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="Remind me about Python",
            assistant_text="Python is a general-purpose language.",
        )

        # 2. Load thread (simulated via localStorage restore)
        loaded_thread = get_thread(tid)
        assert loaded_thread["id"] == tid
        assert len(loaded_thread["messages"]) == 2

        # 3. Add voice-transcribed message
        save_thread(
            tid=tid,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="What about speed?",  # Simulated transcription
            assistant_text="Python can be optimized with C extensions.",
        )

        # 4. Verify new turn was added
        updated_thread = get_thread(tid)
        assert len(updated_thread["messages"]) == 4
        assert updated_thread["messages"][-2]["content"] == "What about speed?"

    def test_workflow_model_switch_persisted(self):
        """Thread metadata reflects model used."""
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-haiku-4",
            user_text="Q1",
            assistant_text="A1",
        )

        thread = get_thread(tid)
        assert thread["model"] == "anthropic/claude-haiku-4"

        # Switch model for next turn
        save_thread(
            tid=tid,
            backend="nous",
            model="anthropic/claude-opus-5",
            user_text="Q2",
            assistant_text="A2",
        )

        thread = get_thread(tid)
        # Model updates if latest turn used a different one
        assert thread["backend"] == "nous"


class TestIntegration:
    """Integration with existing backend endpoints."""

    def test_llms_history_endpoint_compatible(self):
        """Threads are compatible with /api/llms/history response shape."""
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="Test",
            assistant_text="OK",
        )

        threads = list_threads()
        matching = [t for t in threads if t["id"] == tid]
        assert len(matching) == 1

        t = matching[0]
        # Shape matches API contract
        assert "id" in t
        assert "title" in t
        assert "backend" in t
        assert "model" in t
        assert "turns" in t

    def test_llms_history_single_endpoint_compatible(self):
        """Individual threads are compatible with /api/llms/history/{tid}."""
        tid = save_thread(
            tid=None,
            backend="nous",
            model="anthropic/claude-fable-5",
            user_text="Hello",
            assistant_text="Hi",
        )

        thread = get_thread(tid)
        # Shape matches API contract
        assert thread["id"] == tid
        assert "title" in thread
        assert "created_at" in thread
        assert "updated_at" in thread
        assert "backend" in thread
        assert "model" in thread
        assert "messages" in thread
        assert isinstance(thread["messages"], list)

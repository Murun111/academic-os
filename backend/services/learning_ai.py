"""AI Learning Generator and Socratic Tutor for Academic OS.

Leverages the local / cloud LLM Hub to generate structured flashcards,
practice quizzes, study guides, and Socratic dialogue from topics,
courses, and documents.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from backend.llm_hub import ChatMessage, get_backend, status_all


async def _hub_chat(messages: list[ChatMessage]) -> Optional[str]:
    """Chat via the first online llm_hub backend; None if none is reachable."""
    status = await status_all()
    for name, probe in status.items():
        if not probe.online:
            continue
        backend = get_backend(name)
        models = probe.models or await backend.models()
        model_id = models[0].id if models else ""
        res = await backend.chat(messages, model_id)
        return res.content
    return None


class LearningAIUnavailable(Exception):
    """No LLM backend reachable, or the call to it failed. Router maps to 503."""


class LearningAIBadOutput(Exception):
    """The LLM answered but the output could not be parsed. Router maps to 502."""


async def _ai_call(messages: list[ChatMessage]) -> str:
    try:
        content = await _hub_chat(messages)
    except Exception as e:
        raise LearningAIUnavailable(f"The AI model failed to respond: {e}") from e
    if content is None:
        raise LearningAIUnavailable("No AI model is running. Start Ollama or set up Local AI in Settings.")
    if not content.strip():
        raise LearningAIBadOutput("The AI model returned an empty answer. Try again.")
    return content


def _extract_json_block(text: str) -> Optional[Any]:
    """Extract JSON data from code blocks or raw text."""
    # Look for ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        content = match.group(1).strip()
    else:
        content = text.strip()

    try:
        return json.loads(content)
    except Exception:
        # Try finding the first [ or { to last ] or }
        first_b = min([i for i in [content.find('['), content.find('{')] if i != -1], default=-1)
        last_b = max([content.rfind(']'), content.rfind('}')])
        if first_b != -1 and last_b != -1 and last_b > first_b:
            try:
                return json.loads(content[first_b:last_b+1])
            except Exception:
                pass
    return None


def _str(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ("" if v is None else str(v).strip())


def _str_list(v: Any) -> list[str]:
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    return [x for x in (_str(i) for i in v) if x]


def _normalize_cards(raw: list[Any]) -> list[dict[str, Any]]:
    """Coerce LLM flashcards to the documented shape; drop ones missing front/back."""
    out = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        front, back = _str(c.get("front")), _str(c.get("back"))
        if not front or not back:
            continue
        out.append({
            "front": front, "back": back,
            "hint": _str(c.get("hint")), "explanation": _str(c.get("explanation")),
            "tags": _str_list(c.get("tags")),
        })
    return out


def _normalize_questions(raw: list[Any]) -> list[dict[str, Any]]:
    """Coerce LLM quiz questions; drop any that cannot be graded."""
    out = []
    for q in raw:
        if not isinstance(q, dict):
            continue
        prompt, answer = _str(q.get("prompt")), _str(q.get("correct_answer"))
        if not prompt or not answer:
            continue
        qtype = _str(q.get("type")) or "multiple_choice"
        options = _str_list(q.get("options"))
        if qtype == "true_false" and not options:
            options = ["True", "False"]
        if qtype in ("multiple_choice", "true_false") and answer not in options:
            continue  # ungradeable: the right answer is not selectable
        out.append({
            "prompt": prompt, "type": qtype, "options": options, "correct_answer": answer,
            "explanation": _str(q.get("explanation")), "concept": _str(q.get("concept")),
        })
    return out


def _normalize_guide(raw: dict[str, Any], topic: str) -> dict[str, Any]:
    return {
        "title": _str(raw.get("title")) or f"{topic} Study Guide",
        "summary_markdown": _str(raw.get("summary_markdown")),
        "key_takeaways": _str_list(raw.get("key_takeaways")),
        "formulas": _str_list(raw.get("formulas")),
        "tags": _str_list(raw.get("tags")),
    }


async def generate_flashcards_ai(
    topic: str,
    context_text: str = "",
    count: int = 5,
    difficulty: str = "medium",
) -> list[dict[str, Any]]:
    """Generate structured flashcards using the active LLM."""
    prompt = f"""You are an elite academic tutor. Create {count} high-yield flashcards for the topic: "{topic}".
Difficulty: {difficulty}.
{"Context / Reference Material: " + context_text if context_text else ""}

Return ONLY a valid JSON array of objects with the following keys for each flashcard:
- "front": Clear question, prompt, or concept (string)
- "back": Concise, precise answer or explanation (string)
- "hint": A subtle helpful hint (string)
- "explanation": Deeper academic context or why this matters (string)
- "tags": Array of 1-3 short keyword tags (list of strings)

Format example:
[
  {{
    "front": "What is the primary function of Mitochondria?",
    "back": "To produce ATP through cellular respiration.",
    "hint": "Cellular powerhouse",
    "explanation": "Mitochondria generate most of the chemical energy needed to power biochemical reactions via oxidative phosphorylation.",
    "tags": ["Biology", "Cell Structure"]
  }}
]
"""
    content = await _ai_call([ChatMessage(role="user", content=prompt)])
    parsed = _extract_json_block(content)
    cards = _normalize_cards(parsed) if isinstance(parsed, list) else []
    if not cards:
        raise LearningAIBadOutput("The AI model returned flashcards in an unreadable format. Try again.")
    return cards[:count]


async def generate_quiz_ai(
    topic: str,
    context_text: str = "",
    num_questions: int = 4,
    difficulty: str = "medium",
) -> list[dict[str, Any]]:
    """Generate structured multiple-choice & concept questions using the active LLM."""
    prompt = f"""You are a university professor creating a practice quiz on "{topic}".
Difficulty: {difficulty}.
Number of questions: {num_questions}.
{"Context: " + context_text if context_text else ""}

Return ONLY a valid JSON array of objects with the following keys for each question:
- "prompt": The question text (string)
- "type": "multiple_choice" or "true_false" (string)
- "options": Array of 4 option strings (for multiple_choice) or ["True", "False"] (for true_false)
- "correct_answer": The exact string matching one of the options (string)
- "explanation": Step-by-step reasoning explaining why the correct answer is right and why distractors are wrong (string)
- "concept": Specific sub-concept being tested (string)

Format example:
[
  {{
    "prompt": "Which time complexity represents binary search on a sorted array of n elements?",
    "type": "multiple_choice",
    "options": ["O(1)", "O(log n)", "O(n)", "O(n log n)"],
    "correct_answer": "O(log n)",
    "explanation": "Binary search divides the search space in half at each iteration, resulting in logarithmic time complexity O(log n).",
    "concept": "Algorithm Complexity"
  }}
]
"""
    content = await _ai_call([ChatMessage(role="user", content=prompt)])
    parsed = _extract_json_block(content)
    questions = _normalize_questions(parsed) if isinstance(parsed, list) else []
    if not questions:
        raise LearningAIBadOutput("The AI model returned a quiz in an unreadable format. Try again.")
    return questions[:num_questions]


async def generate_study_guide_ai(
    topic: str,
    context_text: str = "",
) -> dict[str, Any]:
    """Generate a comprehensive, high-yield study guide with key takeaways and formulas."""
    prompt = f"""You are a master academic researcher. Write a high-yield study guide for "{topic}".
{"Context Material: " + context_text if context_text else ""}

Return ONLY a valid JSON object with the following keys:
- "title": Concise guide title (string)
- "summary_markdown": Clear, beautifully structured Markdown text with headings (##), bullet points, and concept explanations (string)
- "key_takeaways": Array of 3-5 high-yield bullet takeaways (list of strings)
- "formulas": Array of 2-4 key equations, rules, or formulas (list of strings)
- "tags": Array of relevant topic tags (list of strings)
"""
    content = await _ai_call([ChatMessage(role="user", content=prompt)])
    parsed = _extract_json_block(content)
    guide = _normalize_guide(parsed, topic) if isinstance(parsed, dict) else None
    if not guide or not guide["summary_markdown"]:
        raise LearningAIBadOutput("The AI model returned a study guide in an unreadable format. Try again.")
    return guide


async def socratic_tutor_response(
    topic: str,
    messages: list[dict[str, str]],
    context: str = "",
) -> str:
    """Provide intelligent Socratic feedback and guidance to deepen comprehension."""
    system_prompt = f"""You are the Academic OS Socratic Tutor.
Your goal is to guide the student toward true understanding of "{topic}" without just giving away answers immediately.
Ask clarifying questions, give intuitive analogies, break down complicated jargon, and challenge their assumptions constructively.
Keep responses concise, encouraging, and academically rigorous.
{"Context for this session: " + context if context else ""}
"""
    formatted = [ChatMessage(role="system", content=system_prompt)]
    for m in messages:
        formatted.append(ChatMessage(role=m.get("role", "user"), content=m.get("content", "")))

    return await _ai_call(formatted)

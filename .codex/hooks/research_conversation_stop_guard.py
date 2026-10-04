from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from typing import Any

BLOCK_REASON = (
    "Rewrite the final user-visible response in ordinary research/writing language. "
    "Preserve the substantive content, but remove Skill/Loom/internal implementation names, "
    "internal file paths or links, command/path/digest details, and quoted internal rules. "
    "If this response asks for a Human Decision, end after the meaningful question/choices "
    "and any human-relevant consequence, then wait for the user's answer. "
    "Do not mention this hook or these rewrite instructions."
)

# Keep this list intentionally narrow and implementation-specific. It is a final-output guard,
# not a generic prose linter.
_BLOCK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("skill-md", re.compile(r"(?i)(?:^|[/\\])SKILL\.md\b")),
    ("agents-md", re.compile(r"(?i)(?:^|[/\\])AGENTS\.md\b")),
    ("research-conversation", re.compile(r"(?i)research[-_/\\ ]conversation(?:[/\\ ]+SKILL\.md)?")),
    ("binding-rule", re.compile(r"Bind a human answer only to that issued request", re.IGNORECASE)),
    ("research-loom", re.compile(r"(?i)\bResearch\s+Loom\b|\bresearch-loom(?:\.cmd)?\b")),
    ("loom-label", re.compile(r"(?i)(?<![A-Za-z])Loom(?![A-Za-z])")),
    ("research-package", re.compile(r"(?i)\bResearch Package\b")),
    ("writer-round-trip", re.compile(r"(?i)\bWriter round[- ]trip\b")),
    ("publication-preview", re.compile(r"(?i)\bPublication preview\b")),
    ("named-skill", re.compile(r"(?i)(?:Writer|Documents?|PDF|research[- ]conversation)\s*(?:Skill|スキル)\b")),
    ("internal-skill-path", re.compile(r"(?i)(?:^|[/\\])skills?[/\\][^\s\])>]+[/\\]SKILL\.md\b")),
    ("canonical-public-path", re.compile(r"(?i)\b(?:canonical|public)\s*(?:/|-)\s*path\b")),
)

_DIAGNOSTIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(?:diagnostic|diagnostics|debug|mechanics|implementation|internal|hook|skill|loom|cli|command|path|digest|request[_ -]?id)\b"),
    re.compile(r"(?:診断|デバッグ|内部|実装|仕組み|フック|hook|スキル|Skill|Loom|コマンド|CLI|パス|ダイジェスト|request[_ -]?id|どの(?:スキル|Skill|コマンド|パス))", re.IGNORECASE),
    re.compile(r"(?:なぜ|どうして).{0,40}(?:確認|質問|回答).{0,30}(?:必要|求め|要求)", re.IGNORECASE),
    re.compile(r"(?:確認|質問|回答).{0,40}(?:なぜ|どうして).{0,30}(?:必要|求め|要求)", re.IGNORECASE),
    re.compile(r"(?i)why.{0,40}(?:confirmation|question|answer).{0,30}(?:required|needed)"),
)


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := _extract_text(item)))
    if isinstance(value, dict):
        for key in ("text", "message", "prompt"):
            direct = value.get(key)
            if isinstance(direct, str):
                return direct
        content = value.get("content")
        if content is not None:
            return _extract_text(content)
    return ""


def _latest_user_prompt_from_value(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        if value.get("role") == "user":
            text = _extract_text(value.get("content", value))
            if text:
                found.append(text)
        if value.get("type") in {"user_message", "user"}:
            text = _extract_text(value)
            if text:
                found.append(text)
        for child in value.values():
            found.extend(_latest_user_prompt_from_value(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_latest_user_prompt_from_value(child))
    return found


def latest_user_prompt(transcript_path: str | None) -> str:
    if not transcript_path:
        return ""
    path = Path(transcript_path)
    if not path.is_file():
        return ""
    latest = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                prompts = _latest_user_prompt_from_value(value)
                if prompts:
                    latest = prompts[-1]
    except OSError:
        return ""
    return latest


def is_explicit_diagnostic_request(prompt: str) -> bool:
    if not prompt:
        return False
    return any(pattern.search(prompt) for pattern in _DIAGNOSTIC_PATTERNS)


def leak_labels(message: str) -> list[str]:
    if not message:
        return []
    return [label for label, pattern in _BLOCK_PATTERNS if pattern.search(message)]


def evaluate(payload: dict[str, Any]) -> tuple[bool, list[str], bool]:
    message = payload.get("last_assistant_message")
    message = message if isinstance(message, str) else ""
    prompt = latest_user_prompt(payload.get("transcript_path"))
    diagnostic = is_explicit_diagnostic_request(prompt)
    labels = leak_labels(message)
    should_block = bool(labels) and not diagnostic and not bool(payload.get("stop_hook_active"))
    return should_block, labels, diagnostic


def _append_probe_log(payload: dict[str, Any], blocked: bool, labels: list[str], diagnostic: bool) -> None:
    target = os.environ.get("RESEARCH_LOOM_CODEX_HOOK_LOG")
    if not target:
        return
    record = {
        "hook_event_name": payload.get("hook_event_name"),
        "session_id": payload.get("session_id"),
        "turn_id": payload.get("turn_id"),
        "stop_hook_active": bool(payload.get("stop_hook_active")),
        "blocked": blocked,
        "labels": labels,
        "diagnostic_exemption": diagnostic,
    }
    try:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        # The guard must not break a Codex turn merely because optional probe logging failed.
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0

    blocked, labels, diagnostic = evaluate(payload)
    _append_probe_log(payload, blocked, labels, diagnostic)

    if blocked:
        print(json.dumps({"decision": "block", "reason": BLOCK_REASON}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

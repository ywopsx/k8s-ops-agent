"""LLM에 보내기 전에 토큰·비밀번호·IP 같은 값을 가린다."""
from __future__ import annotations

import re

MASK = "***"

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Authorization 헤더, Bearer 토큰
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}"), rf"\1 {MASK}"),
    # JWT (ServiceAccount 토큰 등)
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"), MASK),
    # AWS 액세스 키 ID
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), MASK),
    # key=value / key: value 형태의 비밀 값
    (re.compile(r"(?i)\b([a-z0-9_.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)[a-z0-9_.-]*)"
                r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&]+)"), rf"\1\2{MASK}"),
    # URL에 들어간 사용자 정보 (scheme://user:pass@host)
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s@/]+@"), rf"\1{MASK}@"),
    # IPv4 주소
    (re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"), "x.x.x.x"),
]


def mask(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text

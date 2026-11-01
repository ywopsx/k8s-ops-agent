from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Severity(IntEnum):
    INFO = 0
    MEDIUM = 1
    HIGH = 2

    @classmethod
    def parse(cls, value: str) -> "Severity":
        return cls[value.upper()]


@dataclass(frozen=True)
class Finding:
    check: str
    severity: Severity
    kind: str
    name: str
    namespace: str | None
    message: str
    hint: str = ""

    @property
    def ref(self) -> str:
        return f"{self.kind}/{self.namespace}/{self.name}" if self.namespace else f"{self.kind}/{self.name}"


@dataclass
class Snapshot:
    """kubectl get -o json 결과를 kind 이름(복수형, 소문자)별로 담아 둔 것."""

    resources: dict[str, list[dict]] = field(default_factory=dict)

    def items(self, kind: str) -> list[dict]:
        return self.resources.get(kind, [])

    def all_items(self):
        for kind, items in self.resources.items():
            for item in items:
                yield kind, item


def version_tuple(version: str) -> tuple[int, int]:
    """'1.33', 'v1.33.2' 같은 문자열을 (1, 33)으로 바꾼다."""
    parts = version.lstrip("v").split(".")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(f"잘못된 버전 형식: {version!r} (예: 1.33)")
    return int(parts[0]), int(parts[1])

"""Alertmanager webhook JSON에서 분석할 알림 하나를 꺼낸다."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Alert:
    name: str
    namespace: Optional[str]
    pod: Optional[str] = None
    service: Optional[str] = None
    severity: Optional[str] = None
    summary: str = ""
    description: str = ""
    starts_at: str = ""
    labels: dict = field(default_factory=dict)

    def describe(self) -> str:
        lines = [f"알림: {self.name} (severity={self.severity or '-'}, 시작 {self.starts_at or '-'})"]
        for k in sorted(self.labels):
            lines.append(f"- 라벨 {k}={self.labels[k]}")
        if self.summary:
            lines.append(f"- 요약: {self.summary}")
        if self.description:
            lines.append(f"- 설명: {self.description}")
        return "\n".join(lines)


def parse_webhook(payload: dict) -> Alert:
    """webhook 페이로드의 firing 알림 중 첫 번째를 고른다. firing이 없으면 첫 번째 알림을 쓴다."""
    alerts = payload.get("alerts") or []
    if not alerts:
        raise ValueError("webhook 페이로드에 alerts가 없습니다.")
    chosen = next((a for a in alerts if a.get("status") == "firing"), alerts[0])
    labels = {**(payload.get("commonLabels") or {}), **(chosen.get("labels") or {})}
    ann = {**(payload.get("commonAnnotations") or {}), **(chosen.get("annotations") or {})}
    if not labels.get("alertname"):
        raise ValueError("알림에 alertname 라벨이 없습니다.")
    return Alert(
        name=labels["alertname"], namespace=labels.get("namespace"), pod=labels.get("pod"),
        service=labels.get("service"), severity=labels.get("severity"),
        summary=ann.get("summary", ""), description=ann.get("description", ""),
        starts_at=chosen.get("startsAt", ""), labels=labels,
    )


def load_alert(path: str | Path) -> Alert:
    return parse_webhook(json.loads(Path(path).read_text(encoding="utf-8")))

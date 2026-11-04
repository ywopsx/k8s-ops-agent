"""원인 ID 목록. LLM은 원인 후보를 이 목록에서만 고른다(자동 채점용).

시나리오의 정답 4개 외에, 같은 알림에서 헷갈릴 만한 원인을 함께 둔다.
"""
from __future__ import annotations

CAUSES: dict[str, str] = {
    "oom_killed": "컨테이너가 메모리 limit을 넘어 OOMKilled로 종료됨",
    "app_config_error": "애플리케이션 설정·환경변수 누락이나 오류로 시작 직후 종료됨",
    "image_pull_error": "이미지를 받지 못함 (ErrImagePull, ImagePullBackOff)",
    "liveness_probe_failure": "liveness probe 실패로 컨테이너가 재시작됨",
    "readiness_probe_failure": "readiness probe 실패로 Pod가 Ready가 아님",
    "service_selector_mismatch": "Service selector가 Pod 라벨과 맞지 않아 엔드포인트가 없음",
    "service_port_mismatch": "Service port·targetPort가 컨테이너 포트와 맞지 않음",
    "pending_node_selector_mismatch": "nodeSelector·nodeAffinity에 맞는 노드가 없어 Pending",
    "pending_insufficient_resources": "CPU·메모리 요청을 받아 줄 노드가 없어 Pending",
    "other": "위 목록에 없는 원인",
}

# 정답 원인별 런북 파일 (runbooks/ 아래)
RUNBOOKS: dict[str, str] = {
    "oom_killed": "oom-killed.md",
    "app_config_error": "crashloop-config.md",
    "service_selector_mismatch": "service-no-endpoints.md",
    "pending_node_selector_mismatch": "pod-pending-node-selector.md",
}

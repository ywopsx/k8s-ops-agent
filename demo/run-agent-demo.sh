#!/usr/bin/env bash
# 알림 1차 분석 데모: kind에 장애 시나리오 4개를 일으키고, 알림 파일마다 에이전트(모드 C)를 돌려 리포트를 남긴다.
# 사용: ./demo/run-agent-demo.sh [--eval]     정리: kind delete cluster --name ops-agent
#   --eval  리포트를 만든 뒤 평가(시나리오 4 × 3회 × 모드 C·A)까지 돌린다. EVAL_MODEL로 모델을 정한다.
# 노트북 메모리가 작으면 다른 kind 클러스터를 먼저 지우세요.
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER=ops-agent
CTX="kind-$CLUSTER"
NS=shop
KC=out/agent/kubeconfig-viewer
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python

if ! kind get clusters | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER"
fi
kubectl config use-context "$CTX"
K=(kubectl --context "$CTX")

# 네임스페이스와 default ServiceAccount를 먼저 만든다 (run-demo.sh와 같은 이유)
"${K[@]}" create namespace "$NS" --dry-run=client -o yaml | "${K[@]}" apply -f -
for _ in $(seq 60); do
  "${K[@]}" -n "$NS" get serviceaccount default >/dev/null 2>&1 && break
  sleep 1
done
"${K[@]}" apply -f demo/agent/scenarios.yaml

# 에이전트용 읽기 전용(view) kubeconfig
./demo/agent-viewer-kubeconfig.sh "$CLUSTER" "$KC"

pod_of() { "${K[@]}" -n "$NS" get pod -l "app=$1" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true; }

wait_for() {   # wait_for <설명> <초> <조건 명령...>
  local desc=$1 secs=$2; shift 2
  for _ in $(seq "$secs"); do
    if "$@" >/dev/null 2>&1; then echo "  ✓ $desc"; return 0; fi
    sleep 1
  done
  echo "  ✗ $desc (${secs}초 안에 확인하지 못함)"; return 1
}
oom_seen()      { [ "$("${K[@]}" -n "$NS" get pod -l app=report-worker -o jsonpath='{.items[0].status.containerStatuses[0].lastState.terminated.reason}')" = OOMKilled ]; }
crash_seen()    { [ "$("${K[@]}" -n "$NS" get pod -l app=order-sync -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}')" -ge 2 ]; }
checkout_up()   { "${K[@]}" -n "$NS" wait --for=condition=Available deployment/checkout-api --timeout=1s; }
pending_seen()  { [ "$("${K[@]}" -n "$NS" get pod -l app=batch-runner -o jsonpath='{.items[0].status.conditions[?(@.type=="PodScheduled")].reason}')" = Unschedulable ]; }

echo "시나리오가 장애 상태가 될 때까지 기다리는 중..."
wait_for "A report-worker: lastState OOMKilled" 240 oom_seen
wait_for "B order-sync: 재시작 2회 이상" 240 crash_seen
wait_for "C checkout-api: Pod Ready (Service 엔드포인트는 비어 있어야 함)" 180 checkout_up
wait_for "F batch-runner: Unschedulable" 120 pending_seen
"${K[@]}" -n "$NS" get pods -o wide
echo "checkout-api 엔드포인트: '$("${K[@]}" -n "$NS" get endpoints checkout-api -o jsonpath='{.subsets}')' (비어 있어야 함)"

# 알림 파일: 템플릿의 Pod 이름과 시작 시각을 채운다
mkdir -p out/agent/alerts
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
"$PY" - "$NOW" <<'EOF'
import json, subprocess, sys
from pathlib import Path
now = sys.argv[1]
for s in json.loads(Path("demo/agent/scenarios.json").read_text()):
    text = Path("demo/agent/alerts", s["alert"]).read_text().replace("__STARTS_AT__", now)
    if s["app"]:
        pod = subprocess.run(["kubectl", "--context", "kind-ops-agent", "-n", "shop", "get", "pod", "-l", f"app={s['app']}",
                              "-o", "jsonpath={.items[0].metadata.name}"], capture_output=True, text=True, check=True).stdout
        text = text.replace("__POD__", pod)
    Path("out/agent/alerts", s["alert"]).write_text(text)
    print(f"  알림 파일: out/agent/alerts/{s['alert']}")
EOF

echo "에이전트 실행 (모드 C)..."
for f in out/agent/alerts/*.json; do
  "$PY" -m agent analyze --alert "$f" --kubeconfig "$KC" ${AGENT_MODEL:+--model "$AGENT_MODEL"} || true
done

if [ "${1:-}" = "--eval" ]; then
  "$PY" -m agent eval --kubeconfig "$KC" --repeats "${EVAL_REPEATS:-3}" --modes c,a ${EVAL_MODEL:+--model "$EVAL_MODEL"}
fi

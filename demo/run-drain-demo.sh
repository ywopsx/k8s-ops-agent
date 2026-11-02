#!/usr/bin/env bash
# drain 검증 데모: 노드 3개 kind 클러스터에 문제를 심고, worker 하나를 실제로 cordon·drain한다.
# 사용: ./demo/run-drain-demo.sh        정리: kind delete cluster --name preflight-rehearsal
# 노트북 RAM이 작으면 preflight-demo 클러스터를 먼저 지우세요: kind delete cluster --name preflight-demo
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER=preflight-rehearsal
CTX="kind-$CLUSTER"
W1="$CLUSTER-worker"
W2="$CLUSTER-worker2"
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python

if ! kind get clusters | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER" --config rehearsal/kind-config.yaml
fi
kubectl config use-context "$CTX"
K=(kubectl --context "$CTX")

# AZ 라벨, 그리고 worker1에만 옛 노드그룹 라벨을 붙인다.
# legacy-batch는 worker1에만 뜰 수 있어서, worker1을 drain하면 옮겨 갈 노드가 없다 (AL2 → AL2023 전환 때의 장애 재현).
"${K[@]}" label node "$W1" topology.kubernetes.io/zone=demo-zone-a eks.amazonaws.com/nodegroup=ng-legacy --overwrite
"${K[@]}" label node "$W2" topology.kubernetes.io/zone=demo-zone-b --overwrite

# 문제 워크로드를 모두 worker1에 올리기 위해 worker2를 잠시 cordon한다.
"${K[@]}" cordon "$W2"
# 새 네임스페이스의 default ServiceAccount는 컨트롤러가 비동기로 만든다. 그 전에 단독 Pod(debug-shell)를 만들면
# "serviceaccount "default" not found"로 거부되므로, 네임스페이스를 먼저 만들고 ServiceAccount가 생길 때까지 기다린다.
"${K[@]}" create namespace preflight-demo --dry-run=client -o yaml | "${K[@]}" apply -f -
for _ in $(seq 60); do
  "${K[@]}" -n preflight-demo get serviceaccount default >/dev/null 2>&1 && break
  sleep 1
done
"${K[@]}" -n preflight-demo get serviceaccount default >/dev/null
"${K[@]}" apply -f demo/planted-issues.yaml
echo "worker1에 Pod가 뜰 때까지 기다리는 중..."
"${K[@]}" -n preflight-demo wait --for=condition=Available deployment/order-api deployment/payment deployment/legacy-batch --timeout=180s
"${K[@]}" -n preflight-demo wait --for=condition=Ready pod/debug-shell --timeout=60s
"${K[@]}" uncordon "$W2"
# zone-spread의 두 번째 Pod는 AZ 분산 제약 때문에 zone-b(worker2)에만 갈 수 있어, worker2를 연 뒤에 뜬다.
"${K[@]}" -n preflight-demo wait --for=condition=Available deployment/zone-spread --timeout=120s
sleep 5   # PDB status(disruptionsAllowed)가 계산될 시간
"${K[@]}" -n preflight-demo get pods -o wide

mkdir -p out
"$PY" -m rehearsal drain --node "$W1" --context "$CTX" --timeout 60 --out out/rehearsal || true

#!/usr/bin/env bash
# kind 클러스터를 만들고 문제를 심은 뒤 preflight를 실행한다.
# 사용: ./demo/run-demo.sh        정리: kind delete cluster --name preflight-demo
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER=preflight-demo

if ! kind get clusters | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER"
fi
kubectl config use-context "kind-$CLUSTER"

# kind 노드에는 AZ 라벨이 없다. zone-spread Deployment가 Pending이 아니라 정상으로 뜨도록 붙여 둔다.
kubectl label nodes --all topology.kubernetes.io/zone=demo-zone-a --overwrite

kubectl apply -f demo/planted-issues.yaml
kubectl create -f demo/legacy-flowschema.yaml 2>/dev/null || echo "(FlowSchema 이미 있음)"
kubectl patch flowschema preflight-demo-legacy --type=merge -p \
  '{"metadata":{"annotations":{"kubectl.kubernetes.io/last-applied-configuration":"{\"apiVersion\":\"flowcontrol.apiserver.k8s.io/v1beta3\",\"kind\":\"FlowSchema\",\"metadata\":{\"name\":\"preflight-demo-legacy\"}}"}}}'

echo "Pod가 뜰 때까지 기다리는 중..."
kubectl -n preflight-demo wait --for=condition=Available deployment/order-api deployment/payment deployment/zone-spread --timeout=120s
sleep 5   # PDB status(disruptionsAllowed)가 계산될 시간

mkdir -p out
python3 -m preflight --target-version 1.33 --save-snapshot out/snapshot | tee out/report.md || true
echo
echo "리포트: out/report.md   스냅샷: out/snapshot/"

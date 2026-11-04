#!/usr/bin/env bash
# 에이전트가 쓸 읽기 전용 kubeconfig를 만든다.
# 기본 view ClusterRole만 가진 ServiceAccount의 토큰으로 접속한다. view에는 Secret 읽기 권한이 없다.
# 사용: ./demo/agent-viewer-kubeconfig.sh <kind 클러스터 이름> <출력 파일>
# 토큰은 출력 파일에만 쓰고 화면에 찍지 않는다. 출력 파일은 .gitignore(out/, kubeconfig*)에 걸린다.
set -euo pipefail

CLUSTER=${1:?kind 클러스터 이름}
OUT=${2:?출력 파일}
ADMIN_CTX="kind-$CLUSTER"
VIEW_CTX="kind-$CLUSTER-viewer"   # rehearsal guard가 kind-로 시작하는 컨텍스트만 허용한다
K=(kubectl --context "$ADMIN_CTX")

"${K[@]}" create namespace ops-agent --dry-run=client -o yaml | "${K[@]}" apply -f - >/dev/null
for _ in $(seq 60); do
  "${K[@]}" -n ops-agent get serviceaccount default >/dev/null 2>&1 && break
  sleep 1
done
"${K[@]}" -n ops-agent create serviceaccount ops-agent-viewer --dry-run=client -o yaml | "${K[@]}" apply -f - >/dev/null
"${K[@]}" create clusterrolebinding ops-agent-viewer --clusterrole=view \
  --serviceaccount=ops-agent:ops-agent-viewer --dry-run=client -o yaml | "${K[@]}" apply -f - >/dev/null

SERVER=$("${K[@]}" config view --minify -o jsonpath='{.clusters[0].cluster.server}')
CA_FILE=$(mktemp)
trap 'rm -f "$CA_FILE"' EXIT
"${K[@]}" config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d > "$CA_FILE"
TOKEN=$("${K[@]}" -n ops-agent create token ops-agent-viewer --duration=4h)

mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
KC=(kubectl --kubeconfig "$OUT")
"${KC[@]}" config set-cluster "$ADMIN_CTX" --server="$SERVER" --certificate-authority="$CA_FILE" --embed-certs=true >/dev/null
"${KC[@]}" config set-credentials ops-agent-viewer --token="$TOKEN" >/dev/null
"${KC[@]}" config set-context "$VIEW_CTX" --cluster="$ADMIN_CTX" --user=ops-agent-viewer >/dev/null
"${KC[@]}" config use-context "$VIEW_CTX" >/dev/null
chmod 600 "$OUT"

# 권한 확인: Pod 조회는 되고, Secret 조회와 Pod 삭제는 안 되어야 한다.
ok=$("${KC[@]}" auth can-i list pods -A)
secret=$("${KC[@]}" auth can-i get secrets -A || true)
del=$("${KC[@]}" auth can-i delete pods -A || true)
echo "viewer kubeconfig: $OUT (컨텍스트 $VIEW_CTX) — list pods: $ok, get secrets: $secret, delete pods: $del"
[ "$ok" = yes ] && [ "$secret" = no ] && [ "$del" = no ]

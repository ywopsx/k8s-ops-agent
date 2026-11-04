# Service에 엔드포인트가 없음 — selector 불일치

**확인할 것**
- `kubectl -n <ns> get endpoints <svc>` (또는 EndpointSlice)가 비어 있는지 본다.
- `kubectl -n <ns> get svc <svc> -o jsonpath='{.spec.selector}'`와 대상 Pod의 라벨(`kubectl -n <ns> get pods --show-labels`)을 비교한다.
- Pod가 Running·Ready인데도 엔드포인트가 비어 있으면 selector 불일치다. Pod가 Ready가 아니면 readiness probe를 먼저 본다.

**조치 (사람이 결정)**
1. Service selector를 Pod 템플릿 라벨에 맞게 고친다 (Helm values·매니페스트에서 수정).
2. 라벨을 바꾼 배포가 원인이라면 어느 쪽을 기준으로 맞출지 서비스 담당자와 정한다.

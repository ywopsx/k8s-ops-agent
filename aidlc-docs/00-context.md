# 프로젝트 맥락

이 문서는 프로젝트의 배경, 범위, 결정 사항을 정리한다. 새 세션을 시작할 때 이 문서부터 읽는다.

## 배경

- EKS 클러스터를 매 버전 직접 업그레이드하며 같은 체크리스트를 손으로 확인했고, 확인을 놓친 항목이 장애로 이어졌다.
  - AL2 → AL2023 노드그룹 전환 때, nodeSelector가 노드그룹 이름 라벨(eks.amazonaws.com/nodegroup)에 묶여 새 노드그룹으로 옮길 수 없었다.
  - vpc-cni 애드온 업데이트로 aws-node의 Custom Networking 설정이 기본값으로 덮어써져 신규 Pod가 IP를 받지 못했다.
  - 1.32 업그레이드 전, 제거되는 API(flowcontrol v1beta3)를 kubectl과 jq로 하나씩 확인했다.
- 노드그룹 라벨 문제는 Cluster Autoscaler → Karpenter 전환에서도 똑같이 생긴다 (Karpenter 노드에는 노드그룹 라벨이 없다).
- 참고한 공개 사례: 2026 당근 빌더 밋업 발표 (Karpenter 도입, 옵저버빌리티와 알림 분석 에이전트, 배포 도구의 CLI·MCP 비교).

## 목표

SRE가 반복하던 판단을 에이전트가 먼저 분석하고, 사람은 검토하고 승인하는 클러스터 운영 에이전트를 만든다.
AI-DLC 방식(Inception → Construction → Operations)으로 진행하고, AI가 제안한 것 중 무엇을 승인하고 고쳤는지 docs/AI_USAGE.md에 기록한다.

## 범위

### Unit 1. 노드 교체 사전 점검 (`preflight/`)

- 완료 (v0.1): nodegroup-pinned, pdb-blocks-drain, removed-api, al2-node, vpc-cni-env, unmanaged-pod, single-replica 점검. kind 데모로 검증.
- 다음 할 일 (Unit 2보다 먼저 진행한다)
  1. Karpenter 전환 준비 점검 추가 (`preflight/`)
     - lb-target-instance (MEDIUM): target type이 instance인 Service·Ingress·TargetGroupBinding 찾기. AWS Load Balancer Controller의 instance 모드는 ASG가 아니라 클러스터 노드를 등록하므로 Karpenter 노드에서도 동작한다. 다만 노드로 트래픽을 보내므로 Karpenter의 통합·교체 때 처리 중인 요청이 끊기거나 트래픽이 쏠릴 수 있고, 대상 그룹을 클러스터 밖에서 ASG에 직접 붙였다면 Karpenter 노드는 등록되지 않는다(클러스터에서 확인 불가).
     - topology-spread: AZ 분산 제약이 걸린 워크로드 표시 (DoNotSchedule MEDIUM, ScheduleAnyway INFO)
  2. drain 검증 (`rehearsal/`): kind에서 노드를 실제로 cordon·drain해서, 막힌 Pod와 걸린 시간을 리포트에 남긴다.
  3. 업그레이드 리허설 (`rehearsal/`): kind 1.34 클러스터에 워크로드를 올리고 1.35로 옮겨, 점검이 예측한 문제와 실제 결과를 비교한다.
  4. 조치 계획 초안 (`agent/`): 에이전트가 점검 결과(JSON)를 읽고 업그레이드 순서와 조치 계획 초안을 작성한다. 사람이 승인한 뒤 리허설한다.
  5. Helm으로 배포한 리소스도 점검 (helm get manifest)
  6. MCP 서버: stdio 방식으로 `run_preflight` 도구 하나만 연다. Unit 2 에이전트가 이 도구를 불러 쓴다.

### Unit 2. 알림 1차 분석 에이전트 (예정)

- kind에 Prometheus, Alertmanager, Grafana, Loki를 띄운다 (노트북 RAM 8GB라 가볍게 설정한다).
- 장애 시나리오 5개 정도: OOMKilled, CrashLoopBackOff, Service 포트·selector 오류, NetworkPolicy 차단, CoreDNS 장애
- Alertmanager가 에이전트 webhook을 호출한다 (Slack 게시 방식은 질문지 Q7에서 정한다)
- 에이전트는 PromQL, LogQL, kubectl을 읽기 전용으로 병렬 조회하고, 원인 후보와 런북을 Slack 알림 스레드에 답글로 남긴다.
- 차별점: 시나리오마다 정답 원인을 정해 두고 정확도, 걸린 시간, 토큰 비용을 측정한다. 런북을 줄 때와 안 줄 때를 비교한다.
- Unit 1 점검 도구를 MCP 도구(`run_preflight`)로 제공해서 Unit 2 에이전트가 불러 쓴다.
- 세부 요구사항은 `inception/requirements/requirement-verification-questions.md` 답변으로 정한다.

### 하지 않는 것

- SG/IAM 요청 검토 (범위에서 제외)
- 자체 웹 옵저버빌리티 플랫폼, 코딩 에이전트의 자동 PR
- 실제 AWS 계정에서 실행 (모두 kind에서 재현한다)

## 결정 사항 (2026-11-02)

- 우선순위: Unit 1을 먼저 진행한다. Unit 2는 질문지만 정리해 두고, 답은 사용자가 직접 채운다.
- 디렉터리 역할

  | 위치 | 역할 | 클러스터 변경 | 외부 패키지 |
  | --- | --- | --- | --- |
  | `preflight/` | 결정적인 점검만 한다. LLM을 부르지 않는다 | 안 함 (`kubectl get`만) | 안 씀 (표준 라이브러리) |
  | `rehearsal/` | drain 검증, 업그레이드 리허설 | kind에서만 함 | 필요하면 optional-dependencies |
  | `agent/` | LLM 공통 계층. Unit 1 조치 계획 초안, Unit 2 분석 | 안 함 | optional-dependencies |

- 의존성: `preflight/`는 표준 라이브러리만 쓴다. Unit 2와 에이전트 코드는 외부 패키지를 쓸 수 있고, `pyproject.toml`의 `[project.optional-dependencies]`로 분리한다. 기본 설치(`dependencies = []`)는 그대로 둔다.
- rehearsal/ 안전장치: 실행 전에 현재 kubeconfig 컨텍스트가 `kind-`로 시작하는지 코드에서 확인하고, 아니면 아무것도 하지 않고 멈춘다.
- LLM: Anthropic API를 쓴다. API 키는 환경 변수(`.env`)로만 관리하고 코드·문서·테스트·픽스처에 넣지 않는다. 모델 선택은 Unit 2 요구사항에서 정한다.
- MCP: stdio 서버로 시작하고, 처음에는 `run_preflight` 도구 하나만 연다.

## 원칙

- 읽기 전용: 점검과 분석은 클러스터를 바꾸지 않는다. 결정과 조치는 사람이 한다. 예외는 kind에서만 도는 `demo/`, `rehearsal/`이다.
- 근거를 남긴다: 스냅샷, 리포트, 측정 결과를 파일로 남긴다.
- 한계를 숨기지 않는다: kind에서 재현할 수 없는 것(AWS 전용 기능 등)은 README에 적는다.
- 실제 환경 정보와 비밀 정보는 넣지 않는다.

## 진행 기록

- 2026-10-26: Unit 1 v0.1 작성, 단위 테스트 20개
- 2026-10-30: kind 데모에서 removed-api 미검출 발견 → 데모 수정. 실제 운영 라벨 이름을 일반 예시로 교체
- 2026-11-02: 레포 이름을 k8s-ops-agent로 변경, GitHub에 첫 커밋. Claude Code 규칙(CLAUDE.md)과 권한 설정 추가
- 2026-11-02: AI-DLC Requirements Analysis 시작. 우선순위(Unit 1 먼저), 디렉터리 역할, 의존성, LLM, MCP 방식 결정. Unit 2 질문지를 이 문서와 맞게 수정
- 2026-11-02: lb-target-instance, topology-spread 점검 추가. lb-target-instance의 전제(instance 타입 사용 불가)를 문서 확인 후 바로잡음

## 열린 질문

- Unit 2의 동기: 실제 운영에서 알림 1차 분석을 어떻게 했는지 정리해서 채운다 (질문지 Q13).
- 관측 스택 메모리 기준: 노트북 RAM 8GB에서 kind + Prometheus·Alertmanager·Grafana·Loki에 얼마까지 쓸지, 무엇을 줄이거나 뺄지 (질문지 Q12).

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
  7. replica 한 노드 몰림 점검 (`preflight/`, 가칭 colocated-replicas): replica 2개 이상, PDB 없음, Ready Pod가 모두 같은 노드인 워크로드 찾기. drain 데모에서 `order-api`가 예측 못 한 다운타임으로 나와서 추가함. 계획: `plans/unit1-07-colocated-replicas.md`

### Unit 2. 알림 1차 분석 에이전트 (MVP, 2026-11-04)

포트폴리오용 MVP로 범위를 최소로 했다. 세부 요구사항은 `inception/requirements/requirement-verification-questions.md`의 답변을 따른다.

- 입력: Alertmanager webhook JSON 형식의 알림 파일 (CLI `python -m agent analyze`). 출력: Markdown·JSON 리포트
- 시나리오 4개: OOMKilled, CrashLoopBackOff(설정 오류), Service selector 오류(엔드포인트 없음), Pod Pending(nodeSelector 불일치)
- 분석 구조: C(Pod 상태·Event 수집 → LLM이 읽기 전용 도구를 골라 최대 5회 추가 조회)가 기본. 비교용 A(고정 수집 + LLM 1회)
- 에이전트는 MCP 클라이언트다. 붙이는 MCP 서버: Kubernetes 조회(containers/kubernetes-mcp-server, read_only), preflight(`run_preflight`, 직접 만든 stdio 서버)
- 권한 세 겹: MCP 서버 read_only, 기본 view ClusterRole ServiceAccount kubeconfig(Secret 못 읽음), kind 컨텍스트 확인(rehearsal guard). 에이전트 코드에도 도구 허용 목록을 둔다
- LLM: `claude -p`(내장 도구·MCP·외부 설정을 끈 상태)를 백엔드로 쓰고, 백엔드 인터페이스를 나눠 Anthropic API로 바꿀 수 있게 한다
- 데이터: 상태·Event + 로그 최근 N줄, 토큰·비밀번호·IP 마스킹 후 LLM에 보낸다. 런북은 `runbooks/`에 시나리오별로 둔다
- 평가: 시나리오 4 × 3회 × 모드 A·C, 정답 원인 ID 자동 채점. 정확도·평균 시간·도구 호출 수·토큰. 다른 모델과 한 번 비교
- 다음 단계로 미룬 것: 관측 스택(Prometheus·Alertmanager·Grafana·Loki), webhook 서버, Slack 스레드 답글, NetworkPolicy·CoreDNS 시나리오, 런북 유무 비교, Datadog·GitLab MCP 연동

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
  - 2026-11-04 변경: MVP는 `claude -p`를 백엔드로 쓴다(API 키 불필요). Anthropic API 백엔드는 같은 인터페이스로 나중에 추가한다.
- MCP: stdio 서버로 시작하고, 처음에는 `run_preflight` 도구 하나만 연다.
- MCP 위치(2026-11-04): preflight를 감싼 서버는 `preflight_mcp/`에 둔다. `preflight/`는 계속 표준 라이브러리만 쓰고, MCP SDK 의존은 `preflight_mcp/`와 `agent/`에만 있다.

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
- 2026-11-02: 데모·테스트·픽스처의 실제 환경 이름으로 보이는 값을 일반 값으로 교체. drain 검증(`rehearsal/`) 구현, 단위 테스트 55개
- 2026-11-03: drain 데모를 kind에서 확인. 예측한 6건 모두 기대 결과와 일치, 예측 못 한 다운타임 1건(`order-api`) → 백로그 7번(replica 한 노드 몰림 점검) 계획 추가
- 2026-11-03: colocated-replicas 점검 구현. 보호 효과 없는 PDB(maxUnavailable ≥ replica, minAvailable 0)도 PDB 없음으로 판정. 같은 AZ 몰림은 백로그 후보로 남김. 단위 테스트 75개
- 2026-11-03: 작업 방식 변경 — kind 데모는 Claude가 실행하고 결과는 로그·리포트로 보여 준다. run-demo.sh의 ServiceAccount 경합 오류 수정 후 두 데모 모두 README 기대 결과와 일치 확인. drain 데모의 예측 못 한 문제 0건
- 2026-11-04: Unit 1 마무리. Unit 2 MVP 질문지 답변 확정, `agent/`·`preflight_mcp/`·`runbooks/`·`demo/run-agent-demo.sh` 구현

## 열린 질문

- ~~Unit 2의 동기 (질문지 Q13)~~ → 2026-11-04 답변 완료
- ~~관측 스택 메모리 기준 (질문지 Q12)~~ → 2026-11-04 관측 스택을 MVP 범위에서 빼서 해당 없음. 다음 단계에서 다시 정한다
- 공개 전 git 기록에서 실제 환경 이름 제거: 첫 커밋에 실제 환경 이름으로 보이는 노드그룹 값이 남아 있다. 작업 트리에서는 일반 값으로 바꿨지만 기록에는 남으므로, 레포를 공개하기 전에 기록 정리(history rewrite) 여부와 방법을 정한다.

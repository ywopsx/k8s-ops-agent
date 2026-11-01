# 감사 기록

사용자 입력과 AI의 주요 결정을 시간순으로 남긴다. 사용자 입력은 원문 그대로 적는다.

---

## 2026-11-02T00:41:44+09:00 — Requirements Analysis 시작

- **사용자 입력**: "aidlc-docs 요구사항 정리 시작하자"
- **AI 판단**:
  - Workspace Detection: Brownfield. Unit 1(`preflight/`) v0.1 구현 완료, Unit 2(알림 1차 분석)는 README에 "예정"으로만 정의됨.
  - 다음 작업 대상은 Unit 2로 보고, 범위·알림 소스·실행 형태·분석 방식·Slack 연동·보안 제약을 묻는 질문지를 작성함.
  - Unit 1을 역문서화(Reverse Engineering)할지는 사용자에게 묻기로 함(Q1).
- **생성 파일**: `aidlc-state.md`, `audit.md`, `inception/requirements/requirement-verification-questions.md`

---

## 2026-11-02T00:59:26+09:00 — 우선순위·구조 결정, 질문지 수정

- **사용자 입력**:

  > 제안한 순서대로 진행해 줘. 결정 사항은 아래와 같아.
  >
  > - 우선순위: Unit 1 먼저. Unit 2 질문지는 네가 제안한 대로 고쳐 두고, 답은 내가 나중에 직접 채운다.
  > - 의존성: preflight/는 표준 라이브러리만 유지한다. Unit 2와 에이전트 코드는 외부 패키지를 쓸 수 있고, pyproject.toml의 optional-dependencies로 분리한다.
  > - LLM: Anthropic API를 쓴다. API 키는 환경 변수(.env)로만 관리하고 코드나 문서에 넣지 않는다. 모델 선택은 Unit 2 요구사항에서 정한다.
  > - 클러스터를 바꾸는 검증 코드(drain, 리허설)는 rehearsal/에 둔다. 실행 전에 현재 컨텍스트가 kind-로 시작하는지 확인하고, 아니면 멈춘다.
  > - Unit 1의 조치 계획 초안(LLM)은 agent/ 공통 계층에 둔다. preflight/는 결정적인 점검만 한다.
  > - MCP: stdio 서버로, 처음에는 run_preflight 도구 하나만 연다.
  > - 관측 스택 메모리 기준과 Unit 2 동기(Q13)는 열린 질문으로 남긴다.
  >
  > 문서 수정안을 diff로 먼저 보여 줘. 내가 승인하면 반영하고, 그다음 Unit 1 백로그 1번(lb-target-instance, topology-spread)의 구현 계획을 제안해 줘.

- **AI 판단**:
  - 결정 사항을 `00-context.md`의 "결정 사항" 절과 Unit 1 백로그(위치 표시)에 반영. 원칙의 읽기 전용 예외에 `rehearsal/` 추가.
  - `CLAUDE.md`의 의존성 설명과 작업 규칙(클러스터 변경 예외, API 키)을 결정에 맞게 수정.
  - Unit 2 질문지를 `00-context.md`와 맞춤: 이미 정해진 것(Alertmanager, PromQL·LogQL, Anthropic API, Slack 스레드, 정확도·시간·비용 측정)은 질문에서 빼고 "정해진 것"으로 옮김. 남은 결정(시나리오, 실행 형태, 분석 구조, 모델 선택, LLM에 보내는 데이터, 스레드 연결 방식, 채점 방식, 메모리 기준)을 질문으로 다시 씀.
  - Reverse Engineering(구 Q1)은 생략으로 기록. Unit 1 먼저 진행하되 기존 문서로 충분하다고 판단함 — 사용자가 다르게 보면 되돌린다.
- **사용자 검토**: "승인. 단, 질문지의 "이미 정해진 것" 중 입력 항목을 "Alertmanager가 에이전트 webhook을 호출한다 (Slack 게시 방식은 Q7에서 정한다)"로 고치고, 00-context.md의 같은 내용도 맞춰 줘."
  - 반영: Alertmanager가 Slack에 직접 게시하는지는 정해지지 않은 것으로 보고, 질문지와 `00-context.md`의 입력 항목을 webhook 호출만으로 고침.
- **수정 파일**: `CLAUDE.md`, `00-context.md`, `aidlc-state.md`, `audit.md`, `inception/requirements/requirement-verification-questions.md`

---

## 2026-11-02T02:25:45+09:00 — Unit 1 백로그 1번 구현 (lb-target-instance, topology-spread)

- **사용자 입력**:

  > 1. lb-target-instance는 MEDIUM으로 하고, 00-context.md의 전제 문장을 네 설명대로 고쳐 줘.
  >    나도 AWS Load Balancer Controller 문서에서 instance 모드가 ASG가 아니라 클러스터 노드(Node 라벨로 선택)를 등록한다는 걸 확인했어.
  >    구현 전에 현재 Karpenter 공식 문서도 확인해 줘.
  > 2. topology-spread는 DoNotSchedule은 MEDIUM, ScheduleAnyway는 INFO로 한다.
  > 3. TargetGroupBinding도 포함한다. collect.py에서는 "리소스 종류가 없음"일 때만 경고 없이 넘어가고, 권한 오류 같은 다른 실패는 지금처럼 경고를 낸다. 이 두 경우를 구분하는 테스트도 넣어 줘.
  > 4. 데모에서는 kind 노드에 topology.kubernetes.io/zone 라벨을 붙여서, zone 제약 Deployment가 Pending이 아니라 정상으로 뜬 상태에서 검출되게 해 줘.
  > 5. AI_USAGE.md 기록은 초안만 보여 줘. 내가 확인하고 직접 넣을게.
  >
  > 이대로 구현해 줘. 끝나면 pytest 결과와 바뀐 파일 목록을 보여 주고, run-demo.sh는 내가 직접 돌릴게.

- **AI 판단**:
  - lb-target-instance의 원래 전제("Karpenter 노드는 ASG에 속하지 않아 instance 타입을 쓸 수 없다")가 정확하지 않다고 보고 제안함. 사용자가 LBC 문서로 확인한 뒤 MEDIUM으로 결정.
  - Karpenter 공식 문서 확인: 현재 FAQ(v1.15)와 EKS Best Practices의 Karpenter 장에는 LB target type 언급이 없음. IP 모드 권장은 예전 Karpenter FAQ(v0.13 등)와 EKS Load Balancing 모범 사례에 있음. 현재 FAQ는 AZ 분산에 minDomains를 권장 → topology-spread 조치 문구에 반영.
  - 계획에 없던 추가: `ingressclasses`를 수집해 이름이 alb가 아닌 LBC IngressClass와 기본 IngressClass도 판정. 지역 키는 `failure-domain.beta.kubernetes.io/zone`도 인정. `whenUnsatisfiable`이 없으면 기본값 DoNotSchedule로 판정.
  - collect.py: "리소스 종류가 없음"은 모든 kind에서 경고 없이 건너뜀. 그 밖의 실패는 기존처럼 경고.
  - 사용자 검토로 수정: "리소스 종류 없음"을 넘기는 것은 OPTIONAL kind(targetgroupbindings)로 한정. 기본 리소스가 없다고 나오면 경고 — 점검을 못 했는데 문제없음처럼 보이면 안 되기 때문(사용자 지적). 테스트 `test_missing_core_kind_still_warns` 추가.
- **수정 파일**: `preflight/checks.py`, `preflight/report.py`, `preflight/collect.py`, `tests/test_checks.py`, `tests/test_cli.py`, `tests/test_collect.py`(신규), `tests/fixtures/snapshot/{deployments,services,ingresses,targetgroupbindings}.json`, `demo/planted-issues.yaml`, `demo/run-demo.sh`, `README.md`, `00-context.md`, `aidlc-state.md`

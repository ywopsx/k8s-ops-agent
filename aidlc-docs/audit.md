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
- **검증**: pytest 33개 통과. kind 데모(`kind-preflight-demo`)에서 storefront-web·storefront-nlb·zone-spread가 MEDIUM으로 검출되고, ip 모드 order-api는 나오지 않음. TargetGroupBinding CRD가 없어도 경고 없음.

---

## 2026-11-02 — Unit 1 백로그 2번(drain 검증) 계획 작성

- **사용자 입력**: "Unit 1 백로그 2번(drain 검증) 구현 계획을 제안해 줘. 코드는 아직 쓰지 마. 계획은 aidlc-docs/plans/unit1-02-drain.md 파일로도 남겨 줘."
- **AI 판단**:
  - 직접 eviction 루프, 별도 멀티 노드 kind 클러스터, 단독 Pod에 `--force` 사용 안 함, 항상 uncordon을 추천안으로 제시. 사용자 결정은 계획 파일의 `[결정]:` 칸으로 받음.
  - 데모·테스트·픽스처에 실제 환경 이름으로 보이는 노드그룹 값이 남아 있어, 일반 값으로 바꿀지 결정 항목에 추가.
- **사용자 지시**: "audit.md에 실제 이름으로 보이는 값(노드그룹 이름 등)을 그대로 적지 마. \"실제 환경 이름으로 보이는 노드그룹 값\"처럼 이름 없이 써 줘. 앞으로 모든 문서와 커밋 메시지에서도 같은 규칙을 지켜 줘. 이 규칙을 CLAUDE.md 작업 규칙에도 추가해 줘."
  - 반영: 계획 파일에서 해당 값을 지우고 이름 없이 설명. `CLAUDE.md` 작업 규칙에 추가.
- **생성·수정 파일**: `plans/unit1-02-drain.md`(신규), `aidlc-state.md`, `CLAUDE.md`

---

## 2026-11-02 — Unit 1 백로그 2번(drain 검증) 결정과 구현

- **사용자 입력** (결정):

  > 결정은 모두 추천안대로 한다.
  > ① eviction 루프 ② drain 전용 클러스터(worker 2) ③ --force 없음 ④ 항상 uncordon ⑤ 노드그룹 값을 ng-legacy로 교체 ⑥ ask에 kubectl cordon, kubectl uncordon, kubectl create --raw, python3 -m rehearsal, ./demo/*.sh 추가
  >
  > 추가로 반영해 줘.
  > - eviction이 500(한 Pod에 PDB가 여러 개)일 때도 PDB 관련 막힘으로 분류하고 테스트에 넣어 줘.
  > - 리포트의 "PDB에 막힘" 설명에, EKS 관리형 노드그룹 업그레이드는 15분 동안 evict하지 못하면 PodEvictionFailure로 실패한다는 기준을 적어 줘. 공식 문서로 확인한 뒤 넣어 줘.

- **사용자 입력** (구현 시작): "커밋했어. 계획 파일의 [결정] 칸을 채우고 drain 검증 구현을 시작해 줘. 데모(run-drain-demo.sh)는 내가 직접 돌릴게."
- **AI 판단**:
  - ⑤는 먼저 레포 전체를 검색해 이름을 가린 목록으로 확인받은 뒤 교체함(사용자 커밋 36ff5d5).
  - EKS 공식 문서 확인: "Understand each phase of node updates"에 "Pod가 15분 안에 빠져나가지 않고 force 플래그가 없으면 PodEvictionFailure로 실패", 알려진 원인으로 "Aggressive PDB 또는 같은 Pod를 가리키는 PDB 여러 개"가 있음 → 리포트 문구와 출처 링크에 반영.
  - ⑥에 더해 `.venv/bin/python -m rehearsal *`도 `ask`에 넣음(`.venv` 사용 규칙 때문에 같은 명령의 다른 경로).
  - 계획과 달라진 점: 예측 비교를 `rehearsal/compare.py`로 분리, 결과 파일을 `out/rehearsal/<시각>/` 한 디렉터리로 모음. 계획 파일에 표시함.
  - 설계상 판단: eviction과 대체 Pod 대기는 하나의 타임아웃을 공유. "다운타임 가능"은 evict 시점에 같은 컨트롤러의 다른 Ready Pod가 없었는지로 판단(실제 요청 실패 측정 아님). 시스템 네임스페이스는 `--include-system` 없이는 예측 비교에서 제외(preflight와 같은 기준).
  - 데모 기대 결과에 "order-api(replica 2, PDB 없음)가 한 노드에 몰려 있으면 동시에 내려감 → 예측 못 함·발생"을 넣음. 현재 점검이 놓치는 경우라 다음 점검 후보가 될 수 있음.
- **생성·수정 파일**: `rehearsal/`(신규: `__init__.py`, `__main__.py`, `cli.py`, `guard.py`, `kube.py`, `drain.py`, `compare.py`, `report.py`, `kind-config.yaml`), `demo/run-drain-demo.sh`(신규), `tests/rehearsal_fakes.py`·`test_rehearsal_drain.py`·`test_rehearsal_report.py`(신규), `.claude/settings.json`, `README.md`, `CLAUDE.md`, `plans/unit1-02-drain.md`, `00-context.md`, `aidlc-state.md`
- **검증**: pytest 55개 통과. kind 데모는 사용자가 실행 예정.

---

## 2026-11-03T00:41:25+09:00 — drain 데모 결과 기록, 백로그 7번(replica 한 노드 몰림 점검) 계획

- **사용자 입력** (커밋 요청): "이번만 네가 커밋해 줘. 먼저 git status와 git diff --stat을 보여 주고, out/이나 .env가 없으면 아래 메시지로 커밋해 줘. \"Unit 1 백로그 2번: drain 검증(rehearsal) 추가 - kind 데모로 검증, 예측 6건 일치, 예측 못 한 다운타임 1건(order-api) 발견\" push는 내가 승인할게."
  - 반영: `out/`·`.env`가 없음을 확인하고 커밋 a0e29ea 생성. push는 하지 않음.
- **사용자 입력** (문서 갱신):

  > 데모는 내가 다른 터미널에서 돌렸고, 기대 결과와 모두 맞았어. 리포트는 out/rehearsal/20261103-000339/에 있으니 직접 읽고 그 수치를 그대로 써 줘.
  > aidlc-state.md와 audit.md를 데모 결과로 갱신해 줘. AI_USAGE.md에는 넣지 말고, 넣을 내용만 초안으로 보여 줘.
  > 그리고 order-api처럼 "replica 2개 이상, PDB 없음, Ready Pod가 모두 같은 노드"인 경우를 잡는 점검을 백로그에 추가해 줘. 계획만, 코드는 아직 쓰지 마.
  > 문서 갱신은 커밋 하나로 따로 만들어 주고, 그다음 push해 줘. push는 내가 승인할게.

- **데모 결과** (`out/rehearsal/20261103-000339/drain-preflight-rehearsal-worker.{md,json}`에서 그대로 옮김):
  - 컨텍스트 `kind-preflight-rehearsal`, 노드 `preflight-rehearsal-worker`, 시작 2026-11-03T00:03:39, 전체 61.8초, 타임아웃 60초, uncordon 함
  - PDB에 막힘 1(`payment`, 429로 21회 시도) · 재배치 실패 2(`legacy-batch` evict 2.3초, `zone-spread` evict 3.4초) · 컨트롤러 없음 1(`debug-shell`) · evict 실패 0 · 재배치 완료 2(`order-api` 2개) · 건너뜀 2(DaemonSet)
  - 예측 비교 7행: 예측함·발생 5, 예측함·발생 안 함 1(`payment`의 `single-replica` — evict되지 않았으므로, README 기대대로), 예측 못 함·발생 1(`order-api` 다운타임 가능)
  - `order-api`: 두 Pod가 2.6초·2.8초에 evict, 대체 Pod Ready까지 6.5초·6.2초. 두 번째 Pod evict 시점에 다른 Ready Pod가 없었음
- **AI 판단**:
  - README의 데모 기대 결과 표와 리포트가 모두 맞는 것을 확인. 다만 `plans/unit1-02-drain.md` 5장 표는 구현 중 바뀐 내용(`zone-spread` 재배치 실패, `order-api` 다운타임 가능)이 반영되지 않았음 → 상태를 완료로 바꾸고 README 표를 따른다고 표시함.
  - 새 점검은 백로그 7번으로 추가(기존 번호 3~6은 그대로 둠). 추천안: 이름 `colocated-replicas`, MEDIUM, Pod와 워크로드는 selector로 연결, 노드가 하나뿐인 클러스터도 그대로 보고, 시스템 네임스페이스 기본 제외. `selector_matches`를 `rehearsal/`에서 `preflight/`로 옮기는 것을 포함(의존 방향 유지).
  - 노드가 하나인 `preflight-demo`에서는 `order-api`, `zone-spread`가 새로 검출되므로 README 기대 결과 표를 고쳐야 한다는 점을 결정 항목(④)에 적음.
- **생성·수정 파일**: `aidlc-state.md`, `audit.md`, `00-context.md`, `plans/unit1-02-drain.md`, `plans/unit1-07-colocated-replicas.md`(신규)

---

## 2026-11-03T01:21:04+09:00 — 백로그 7번(colocated-replicas) 결정과 구현

- **사용자 입력**:

  > 백로그 7번 결정은 추천안대로 하되, ③만 보완해 줘.
  > PDB가 있어도 maxUnavailable이 replica 수 이상이거나(100% 포함) minAvailable이 0이면 보호 효과가 없으니 "PDB 없음"과 같이 검출 대상으로 본다. 이 경우도 테스트에 넣어 줘.
  > 같은 AZ에 몰린 경우는 이번 범위에서 빼고 백로그 후보로만 적어 줘.
  >
  > AI_USAGE.md 초안은 내가 확인했으니 그대로 넣어 줘.
  >
  > 그다음 백로그 7번을 구현해 줘. 끝나면 pytest 결과와 바뀐 파일 목록을 보여 주고, run-demo.sh 결과가 README 표와 맞는지는 내가 직접 돌려서 확인할게.

- **AI 판단**:
  - 보완한 ③의 해석: maxUnavailable 퍼센트는 Kubernetes처럼 올림해서 Pod 수로 바꾼 뒤 replica 수와 비교(`100%`, replica 2에서 `2`·`3`은 보호 효과 없음, `50%`는 1이라 보호). minAvailable은 `0`·`0%`만 보호 효과 없음으로 봄(`50%`, `1` 등은 두 번째 eviction을 막음).
  - 사용자 지시에 없던 판단: 값을 해석할 수 없거나 minAvailable·maxUnavailable이 모두 없는 PDB는 보호로 봄(추측으로 검출하지 않음). selector가 없는 PDB는 policy/v1처럼 아무 Pod도 고르지 않는 것으로 봄. 여러 PDB 중 보호 효과 있는 것이 하나라도 있으면 검출하지 않음.
  - Ready 판정은 `status.conditions`의 Ready=True와 `spec.nodeName`으로 하고, 삭제 중(deletionTimestamp)인 Pod는 뺌.
  - `selector_matches`를 `rehearsal/compare.py`에서 `preflight/checks.py`로 옮기고, `rehearsal`은 `preflight`에서 import(의존 방향 유지). 기존 테스트의 import 경로는 그대로 동작.
  - `rehearsal` 예측 비교에 colocated-replicas를 "다운타임 가능" 예측으로 추가 → drain 데모의 `order-api`는 "예측함·발생"이 될 것으로 기대(데모로는 아직 확인 안 함).
  - 노드가 하나인 `preflight-demo`에서는 `order-api`, `zone-spread` Deployment가 새로 검출되므로 README의 run-demo 기대 결과 표와 문구("order-api는 나오지 않아야 한다")를 고침. ip 모드 Service `order-api`가 lb-target-instance에 나오지 않는다는 기대는 그대로.
  - 확인한 docs/AI_USAGE.md 초안을 그대로 넣음.
- **수정 파일**: `preflight/checks.py`, `preflight/report.py`, `rehearsal/compare.py`, `tests/test_checks.py`, `tests/test_rehearsal_report.py`, `README.md`, `docs/AI_USAGE.md`, `plans/unit1-07-colocated-replicas.md`, `00-context.md`, `aidlc-state.md`, `audit.md`
- **검증**: pytest 75개 통과(새 테스트 20개). 픽스처 스냅샷 실행에서 colocated-replicas 미검출(픽스처 Pod에 nodeName 없음). kind 데모(`run-demo.sh`, `run-drain-demo.sh`)는 사용자가 실행 예정.

---

## 2026-11-03T01:58:00+09:00 — 작업 방식 변경, 데모 스크립트 오류 수정, 두 데모 확인

- **사용자 입력**:

  > 작업 방식을 바꿀게.
  > 1. CLAUDE.md에서 "데모는 사용자가 직접 실행한다"는 규칙을 "kind 데모는 Claude가 실행해도 된다. 대신 결과는 로그와 리포트를 근거로 보여 준다"로 바꿔 줘. .claude/settings.json의 ask에서 ./demo/*.sh와 python3 -m rehearsal는 빼 줘. git push는 ask에 그대로 둔다.
  > 2. run-demo.sh의 Forbidden 오류 원인을 찾아서 고치고, run-demo.sh와 run-drain-demo.sh를 다시 돌려서 README 기대 결과 표와 비교해 줘. 클러스터는 메모리 때문에 하나씩만 띄워.
  > 3. 다 맞으면 문서를 갱신하고 커밋해 줘. push 직전에 멈추고, 원인과 고친 내용, 두 데모 결과 요약, git diff --stat을 보여 줘.

- **AI 판단**:
  - CLAUDE.md에는 "데모는 사용자가 직접 실행한다"는 문장이 그대로 있지 않아서(이전 대화에서 사용자가 직접 돌리겠다고 한 것이 관례였음), 작업 규칙에 새 줄로 추가함. 클러스터를 하나씩만 띄운다는 조건도 함께 적음.
  - settings.json `ask`에서 `./demo/run-demo.sh`, `./demo/*.sh`, `python3 -m rehearsal *`와 같은 명령의 다른 경로인 `.venv/bin/python -m rehearsal *`도 뺌. `git push *`, `kind delete *`, `kubectl delete/cordon/uncordon/create --raw`는 그대로 둠.
  - Forbidden 원인(로그 근거): `kubectl apply`가 같은 호출에서 `preflight-demo` 네임스페이스와 단독 Pod `debug-shell`을 만드는데, 새 네임스페이스의 `default` ServiceAccount는 컨트롤러가 비동기로 만든다. 그 전에 Pod 생성 요청이 들어가 `serviceaccount "default" not found`로 거부됨. Deployment Pod는 컨트롤러가 나중에 재시도해서 영향이 없었음. `set -e`로 스크립트가 그 자리에서 멈춰 preflight가 돌지 않았고, `out/report.md`는 2026-11-02 파일 그대로였음.
  - 수정: `run-demo.sh`, `run-drain-demo.sh` 모두 네임스페이스를 먼저 만들고 `default` ServiceAccount가 생길 때까지 최대 60초 기다린 뒤 매니페스트를 적용. 같은 매니페스트를 같은 방식으로 적용하는 drain 데모도 같은 경합이 생길 수 있어서 함께 고침.
  - 실행 순서: 남아 있던 `preflight-rehearsal` 삭제 → `run-demo.sh` → `preflight-demo` 삭제 → `run-drain-demo.sh` → `preflight-rehearsal` 삭제. 실행 전 `kubectl config current-context`와 `kind get clusters`로 확인.
- **데모 결과**:
  - `run-demo.sh` (종료 코드 0, 로그에 오류 줄 없음, `out/report.md` 2026-11-03 01:53:29): HIGH 3 · MEDIUM 9 · INFO 0. README 표의 9행(legacy-batch, payment, debug-shell, preflight-demo-legacy, storefront-web, storefront-nlb, zone-spread의 topology-spread·colocated-replicas, order-api의 colocated-replicas)이 모두 나옴. ip 모드 Service `order-api`는 lb-target-instance에 없음, coredns 없음, local-path-provisioner single-replica는 README가 허용한 결과.
  - `run-drain-demo.sh` (종료 코드 0, `out/rehearsal/20261103-015605/`): 전체 61.8초(타임아웃 60초), uncordon 함. PDB에 막힘 1(429로 25회) · 재배치 실패 2 · 컨트롤러 없음 1 · evict 실패 0 · 재배치 완료 2 · 건너뜀 2. 예측 비교 7행: 예측함·발생 6, 예측함·발생 안 함 1(`payment`의 single-replica), 예측 못 함·발생 0. `order-api` 다운타임 가능은 colocated-replicas로 예측함·발생.
- **수정 파일**: `CLAUDE.md`, `.claude/settings.json`, `demo/run-demo.sh`, `demo/run-drain-demo.sh`, `aidlc-state.md`, `00-context.md`, `audit.md`, `plans/unit1-07-colocated-replicas.md`

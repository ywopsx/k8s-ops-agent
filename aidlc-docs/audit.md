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


---

## 2026-11-04T15:35:00+09:00 — Unit 1 마무리, Unit 2 MVP 구현과 평가

- **사용자 입력**:

  > Unit 1은 여기서 마무리하고 Unit 2 MVP를 빠르게 만든다. 포트폴리오에 올리는 게 목표라 범위를 최소로 한다.
  >
  > ## 질문지 답 (requirement-verification-questions.md에 반영)
  > - Q1 시나리오: A OOMKilled, B CrashLoopBackOff, C Service selector 오류(엔드포인트 없음), F Pod Pending(nodeSelector 불일치)
  > - Q2 실행 형태: A CLI. Alertmanager webhook JSON 형식의 알림 파일을 입력으로 받아 분석 리포트(Markdown, JSON)를 출력
  > - Q3 분석 구조: C. 처음에 Pod 상태와 Event만 수집해 LLM에 주고, LLM이 읽기 전용 도구를 골라 추가 조회한다. 도구 호출은 최대 5회. 비교용으로 A(고정 수집 + LLM 1회) 모드도 옵션으로 둔다
  > - Q4 모델: 하나로 개발하고, 평가 때만 다른 모델과 한 번 비교
  > - Q5 LLM 데이터: B 로그 최근 N줄, 토큰·비밀번호·IP 패턴 마스킹
  > - Q6 런북: C 시나리오별 짧은 런북을 runbooks/에 작성해 프롬프트에 넣는다
  > - Q7 Slack: C 이번에는 파일 출력만
  > - Q8 결과: A, B, C, D, F
  > - Q10: A 읽기 전용
  > - Q11: B 정답 원인 ID를 정해 두고 자동 채점, 시나리오당 3회
  > - Q12: 관측 스택을 띄우지 않으므로 해당 없음 (Prometheus, Loki, Grafana는 이번 범위에서 제외)
  > - Q13 동기: 운영 중 알림이 오면 Teams로 들어온 Datadog·CloudWatch 알림을 확인하고, Pod나 서비스 관련 알림이면 kubectl로 Pod 상태와 로그를 하나씩 조회해 1차 원인을 찾았다. AWS DevOps Agent로 알람 원인 분석을 해 보기도 했는데, 이 1차 분석을 쿠버네티스 환경에서 에이전트가 먼저 하게 직접 만들고, 그 정확도를 재 보고 싶었다.
  >
  > ## 구조
  > - agent/ 패키지에 에이전트 루프를 직접 구현한다. 에이전트는 MCP 클라이언트다.
  > - 붙이는 MCP 서버는 두 개:
  >   1. 쿠버네티스 조회: 공개된 Kubernetes MCP 서버(containers/kubernetes-mcp-server 권장)를 쓴다. read_only = true로 실행한다.
  >   2. 업그레이드 사전 점검: preflight를 감싼 MCP stdio 서버를 직접 만든다 (도구: run_preflight). Claude Code에서 붙여 쓰는 방법도 README에 적는다.
  > - 권한은 세 겹으로 막는다: MCP 서버 read_only, 기본 view ClusterRole만 가진 ServiceAccount의 kubeconfig, kind 컨텍스트 확인(rehearsal의 guard 재사용). view라 Secret은 읽지 못한다.
  > - README에 "실무에서는 Datadog MCP, GitLab MCP를 추가로 붙여 지표와 배포 이력까지 보도록 확장할 수 있다"고 설계 의도만 적는다. 실제로 붙이지는 않는다.
  >
  > ## LLM 호출
  > - 지금은 claude -p(비대화형)를 LLM 백엔드로 쓴다. 나중에 Anthropic API로 바꿀 수 있게 백엔드 인터페이스를 분리한다.
  > - 중요: claude -p 호출에서는 Claude Code의 내장 도구(Bash, 파일 읽기·쓰기 등)를 쓸 수 없게 막는다. LLM은 텍스트로 다음 행동(도구 이름과 인자, 또는 최종 결론)만 답하고, 도구 실행은 우리 에이전트 코드가 MCP로 한다. claude --help로 내장 도구를 끄는 옵션을 확인한 뒤 적용하고, 어떻게 막았는지 보여 줘. 막을 방법을 찾지 못하면 구현하지 말고 멈춰.
  > - 토큰과 비용은 claude -p --output-format json 결과에 있으면 기록하고, 없으면 시간만 기록한다고 README에 적는다.
  > - 테스트는 가짜 LLM 백엔드로, 실제 호출을 하지 않는다.
  > - 외부 패키지(MCP SDK 등)는 pyproject의 optional-dependencies(agent)로 분리한다. preflight/는 계속 표준 라이브러리만 쓴다.
  >
  > ## 데모와 평가
  > - demo/run-agent-demo.sh: kind에 시나리오 4개를 일으키고, 각 알림 파일로 에이전트를 돌려 리포트를 남긴다.
  > - eval: 시나리오 4개 × 3회 × 2모드(A, C). 정확도, 평균 시간, 도구 호출 수, 토큰(가능하면)을 표로 만들어 README에 넣는다.
  > - README 맨 위 표의 Unit 2 상태와 설명을 갱신한다.
  >
  > ## 진행 방식
  > - 계획은 짧게 보여 주고, 내 승인 없이 바로 구현해도 된다.
  > - kind 데모와 eval도 네가 돌린다. 클러스터는 메모리 때문에 하나씩만 띄운다.
  > - 실제 환경 이름은 어디에도 넣지 않는다.
  > - 끝나면 결과 요약(정확도 표 포함), 막힌 점, git diff --stat을 보여 주고 push 전에 멈춘다.

- **AI 판단**:
  - `claude -p` 내장 도구 차단(진행 조건): `claude --help`에서 `--tools ""`(모든 내장 도구 끄기)를 찾음. `--strict-mcp-config`(MCP 서버 없음), `--setting-sources ""`(사용자·프로젝트 설정 안 읽음), `--system-prompt`, 빈 임시 cwd(CLAUDE.md 안 읽음)를 함께 씀. 빈 디렉터리에서 실제 실행해 init 이벤트 `tools: []`·`mcp_servers: []`를 확인하고, "Bash로 파일을 만들라"는 요청에 파일이 생기지 않는 것을 확인한 뒤 구현함. 매 호출마다 init 이벤트를 검사해 도구가 있으면 멈추게 함(`ToolsNotDisabledError`). OAuth 로그인을 쓰므로 API 키가 필요한 `--bare`는 쓰지 않음.
  - 토큰·비용: `--output-format json` 대신 `stream-json`을 씀(init 이벤트로 도구 상태를 확인하려고). result 이벤트에 `usage`·`total_cost_usd`가 있어 기록함. 캐시 때문에 `input_tokens`만으로는 입력이 작게 보여, 평가 표의 입력 토큰은 입력+캐시 읽기+캐시 쓰기로 계산.
  - 패키지: node·uv가 없어 PyPI의 `kubernetes-mcp-server==0.1.1`(첫 실행 때 공식 GitHub 릴리스 바이너리를 내려받는 래퍼)과 `mcp==1.30.0`(API가 익숙한 1.x)을 `.venv`에 설치하고 optional-dependencies `agent`에 고정.
  - Kubernetes MCP 서버: `read_only = true`일 때 쓰기 도구 6개가 목록에서 빠지는 것을 read_only=false와 비교해 확인. 에이전트 코드에도 읽기 도구 7개 + `run_preflight` 허용 목록을 둠(사용자 지시의 세 겹 외 추가). view ServiceAccount로 Secret 조회가 forbidden인 것을 MCP 호출로 확인.
  - preflight MCP 서버는 `preflight_mcp/`에 둠(`preflight/`는 표준 라이브러리 유지). preflight의 `[warn]` 출력이 stdio MCP의 stdout(JSON-RPC 통로)을 깨뜨릴 수 있어 가로채 `warnings`로 돌려줌. 이 서버도 kind 컨텍스트에서만 실행.
  - 원인 ID: 정답 4개 + 헷갈리기 쉬운 원인 6개. 워크로드·알림 이름은 원인을 드러내지 않게 정함(A·B는 같은 `KubePodCrashLooping`).
  - 첫 데모에서 B가 도구 호출 없이 맞았는데, 근거가 Pod spec의 command에 적힌 에러 문구였음 → 평가가 공정하지 않다고 보고 스크립트를 ConfigMap으로 옮김. 다시 돌린 B는 `pods_log`로 근거를 찾음.
  - 평가 비용 평균값이 소수 둘째 자리 반올림으로 0.0이 되어 넷째 자리로 고치고, 저장된 runs.json으로 요약을 다시 만듦(재실행 없음).
  - 문서: 질문지 답변 반영, "이미 정해진 것"과 `00-context.md`의 Unit 2 범위·결정을 MVP로 바꿈(관측 스택·webhook·Slack·Anthropic API·런북 유무 비교는 다음 단계). 열린 질문 Q12·Q13 닫음. README Unit 2 절과 평가 표, CLAUDE.md 갱신. README 동기 문단은 제품·메신저 이름을 일반 표현으로 씀.
- **검증**:
  - pytest 100개 통과 (새 테스트 25개, 가짜 LLM 백엔드·가짜 MCP 도구 상자, 실제 호출 없음)
  - `run-agent-demo.sh` (kind 클러스터 `ops-agent` 하나만): 시나리오 4개 장애 상태 확인, 모드 C 4개 모두 정답. 리포트 JSON에 Pod IP 0건(마스킹)
  - 평가: claude-sonnet-5-5 모드 C 12/12(평균 14.48초, LLM 선택 도구 0.58회, $0.0503), 모드 A 12/12(10.55초, $0.0388). claude-haiku-5-5 모드 C 4/4, A 4/4(약 1/17 비용). 정확도가 천장이라 시나리오 변별력이 없고, 이번 시나리오에서는 고정 수집(A)이 더 빠르고 쌌다는 점을 README에 적음
- **생성·수정 파일**: `agent/`(신규), `preflight_mcp/`(신규), `runbooks/`(신규), `demo/agent/`(신규), `demo/run-agent-demo.sh`·`demo/agent-viewer-kubeconfig.sh`(신규), `tests/agent_fakes.py`·`test_agent_llm.py`·`test_agent_loop.py`·`test_agent_runtime.py`(신규), `pyproject.toml`, `README.md`, `CLAUDE.md`, `00-context.md`, `aidlc-state.md`, `audit.md`, `inception/requirements/requirement-verification-questions.md`

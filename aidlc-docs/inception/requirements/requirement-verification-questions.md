# 요구사항 확인 질문 — Unit 2. 알림 1차 분석

각 질문의 `[Answer]:` 뒤에 선택지 문자를 적어 주세요. 여러 개를 고를 수 있는 질문은 `B, C`처럼 적습니다. 맞는 선택지가 없으면 `X)`를 고르고 내용을 적어 주세요. 이유나 조건을 덧붙여 주시면 요구사항 문서에 그대로 반영합니다.

README에 정의된 Unit 2: *알림이 오면 상태를 조회하고 원인 후보와 런북을 Slack 스레드에 남김.*

## 이미 정해진 것 (질문하지 않음)

`00-context.md`에서 정한 내용이다. 바꾸려면 그 문서부터 고친다.

> 2026-11-04 MVP 범위 축소로 아래처럼 바뀌었다. 처음 정한 내용(관측 스택, webhook 서버, Slack 스레드, Anthropic API, 런북 유무 비교)은 다음 단계로 미룬다.

- 환경: kind 클러스터 하나. Prometheus·Alertmanager·Grafana·Loki는 띄우지 않는다. 실제 AWS 계정에서는 실행하지 않는다.
- 입력: Alertmanager webhook JSON 형식의 알림 파일 (CLI 입력)
- 조회: 읽기 전용 MCP 도구로 Kubernetes를 조회한다(PromQL·LogQL 없음). 자동 조치는 하지 않는다.
- 출력: 원인 후보, 근거, 런북, 확인 명령을 Markdown·JSON 파일로 남긴다.
- LLM: 지금은 `claude -p`(내장 도구를 모두 끈 상태)를 백엔드로 쓰고, Anthropic API로 바꿀 수 있게 백엔드 인터페이스를 나눈다. 외부 패키지는 optional-dependencies(`agent`)로 분리한다.
- Unit 1 연동: preflight를 감싼 MCP stdio 서버의 `run_preflight` 도구를 붙인다.
- 평가: 시나리오마다 정답 원인 ID를 정해 두고 정확도, 걸린 시간, 도구 호출 수, 토큰을 측정한다. 분석 구조 A와 C를 비교한다.

---

## 1. 시나리오와 실행 형태

### Q1. MVP 장애 시나리오는 무엇으로 할까요? (여러 개 선택)

`00-context.md`의 후보 5개:

A) OOMKilled
B) CrashLoopBackOff (설정 오류 등 OOM이 아닌 원인)
C) Service 포트·selector 오류 (엔드포인트 없음)
D) NetworkPolicy 차단
E) CoreDNS 장애
F) Pod Pending — nodeSelector 불일치, 리소스 부족 (Unit 1 점검과 연결되는 시나리오)
X) 기타

[Answer]: A, B, C, F — A OOMKilled, B CrashLoopBackOff(설정 오류), C Service selector 오류(엔드포인트 없음), F Pod Pending(nodeSelector 불일치). D(NetworkPolicy)·E(CoreDNS)는 다음 단계.

### Q2. MVP의 실행 형태는 무엇이 좋을까요?

A) CLI — 알림 페이로드(JSON)를 입력으로 받아 분석 결과를 출력. Unit 1처럼 로컬·CI에서 재현하기 쉬움
B) 웹훅 서버 — Alertmanager webhook을 받아 바로 분석하고 Slack에 게시하는 상시 실행 프로세스
C) A로 먼저 만들고, 같은 분석 로직을 B에서 재사용하는 단계적 방식
X) 기타

[Answer]: A — CLI. Alertmanager webhook JSON 형식의 알림 파일을 입력으로 받아 분석 리포트(Markdown, JSON)를 출력한다.

---

## 2. 분석 방식

### Q3. 분석 구조는 어떻게 할까요?

A) 고정 수집 + LLM 추론 — 알림 종류별로 정해 둔 PromQL·LogQL·kubectl 조회를 병렬로 실행하고, 결과를 LLM에 넘겨 원인 후보를 만든다. 조회 횟수·비용이 예측 가능함
B) 도구 호출 에이전트 — LLM이 조회 도구(PromQL, LogQL, kubectl, `run_preflight`)를 스스로 골라 여러 번 호출한다. 유연하지만 시간·비용 편차가 큼
C) A로 1차 수집을 하고, 근거가 부족할 때만 B처럼 추가 조회를 허용한다 (최대 호출 횟수 제한)
X) 기타

[Answer]: C — 처음에 Pod 상태와 Event만 수집해 LLM에 주고, LLM이 읽기 전용 도구를 골라 추가 조회한다. 도구 호출은 최대 5회. 비교용으로 A(고정 수집 + LLM 1회) 모드도 옵션으로 둔다.

### Q4. 모델은 어떻게 고를까요?

A) 처음부터 하나로 정한다 (이유를 함께 적어 주세요)
B) 같은 시나리오를 여러 모델로 돌려 정확도·시간·비용을 비교한 뒤 정한다 (평가 항목에 모델 비교 추가)
C) 저비용 모델을 기본으로 쓰고, 근거가 부족하거나 확신이 낮을 때만 상위 모델로 넘긴다
X) 기타

[Answer]: X — 하나로 개발하고, 평가 때만 다른 모델과 한 번 비교한다.

### Q5. LLM에 보내는 데이터는 어디까지 허용하나요?

A) 리소스 상태, Event, 메트릭 요약만 보낸다. 로그 원문은 보내지 않는다
B) A + 로그 최근 N줄. 토큰·비밀번호·IP 등은 마스킹한 뒤 보낸다
C) 제한 없이 보낸다 (kind 환경이라 민감정보가 없다는 전제)
X) 기타

[Answer]: B — 리소스 상태·Event + 로그 최근 N줄. 토큰·비밀번호·IP 패턴은 마스킹한 뒤 보낸다.

### Q6. 런북은 어디에 두나요?

A) 이 저장소 안에 Markdown으로 둔다 (예: `runbooks/oomkilled.md`)
B) 외부 위키에 있고, 결과에는 링크만 남긴다
C) 아직 없다. 시나리오별 런북을 이번에 같이 작성한다 (A의 위치에)
X) 기타

[Answer]: C — 시나리오별 짧은 런북을 `runbooks/`에 작성해 프롬프트에 넣는다.

---

## 3. 출력과 Slack 연동

### Q7. 에이전트 답글을 원래 알림 메시지의 스레드에 어떻게 붙이나요?

Alertmanager의 Slack 연동은 게시한 메시지의 ID(`ts`)를 돌려주지 않아서, 스레드 답글을 달려면 방법을 정해야 한다.

A) 에이전트가 알림 메시지도 직접 게시한다 — Alertmanager는 webhook만 호출하고, 에이전트가 Bot Token으로 알림을 올린 뒤 그 `ts`에 답글
B) Alertmanager가 Slack에 게시하고, 에이전트는 채널 최근 메시지에서 해당 알림을 찾아 답글 (채널 기록 읽기 권한 필요)
C) MVP는 Slack 없이 Markdown·JSON 파일 출력만 하고, Slack 연동은 다음 단계로
X) 기타

[Answer]: C — 이번에는 파일 출력만 한다. Slack 연동은 다음 단계.

### Q8. 결과에는 무엇을 남길까요? (여러 개 선택)

A) 원인 후보 (가능성 순)와 각 후보의 근거 (어떤 조회 결과를 보고 판단했는지)
B) 조회한 리소스 상태 요약 (Pod 상태, 최근 Event, 메트릭)
C) 런북 링크 또는 조치 절차
D) 사람이 바로 실행해 볼 확인 명령어 (예: `kubectl describe pod ...`)
E) 분석 시점 스냅샷 저장 (Unit 1의 `--save-snapshot`처럼 재현용)
F) 사용한 모델, 토큰 수, 걸린 시간
X) 기타

[Answer]: A, B, C, D, F

### Q9. Slack에 올라가는 정보의 민감정보 처리는 어떻게 하나요?

A) 로그 원문은 올리지 않고, 리소스 상태와 Event 요약만 올린다
B) 로그를 올리되 토큰·비밀번호·IP 등을 마스킹한다
C) Slack에는 요약만 올리고, 결과 전체는 로컬 파일로만 남긴다
X) 기타

[Answer]: 해당 없음 — Q7에서 Slack 게시를 하지 않기로 했다. LLM에 보내는 데이터의 마스킹은 Q5를 따른다.

---

## 4. 원칙과 평가

### Q10. 자동 조치 범위는 어떻게 하나요?

A) Unit 1과 같다 — 읽기 전용, 자동 조치 없음. 결정과 실행은 사람이
B) MVP는 A로 하고, 나중에 Slack 승인 버튼으로 제한된 조치(예: Pod 재시작)를 검토
X) 기타

[Answer]: A — 읽기 전용, 자동 조치 없음.

### Q11. 정확도는 어떻게 채점하나요?

A) 사람이 결과를 보고 직접 채점한다
B) 시나리오마다 정답 원인 ID를 정해 두고, 에이전트가 원인 후보를 정해진 ID 중에서 고르게 해서 자동 채점한다
C) B로 자동 채점하고, 일부 결과는 사람이 다시 확인한다
X) 기타

반복 횟수(시나리오당 몇 번 돌릴지)도 적어 주세요.

[Answer]: B — 정답 원인 ID를 정해 두고 자동 채점한다. 시나리오당 3회.

---

## 5. 열린 질문

### Q12. 관측 스택의 메모리 기준은 어떻게 할까요? (열린 질문)

노트북 RAM 8GB에서 kind 클러스터와 Prometheus·Alertmanager·Grafana·Loki에 얼마까지 쓸지, 넘을 때 무엇을 줄이거나 뺄지 적어 주세요. (예: 전체 4GB 이하, Grafana는 필요할 때만 띄움)

[Answer]: 해당 없음 — 관측 스택을 띄우지 않는다. Prometheus, Loki, Grafana는 이번 범위에서 제외한다.

### Q13. Unit 2를 만들게 된 동기와 실제 경험 (열린 질문)

실제 운영에서 알림 1차 분석을 어떻게 했는지, 반복하던 절차, 에이전트에 꼭 넣고 싶은 것을 적어 주세요. 회사·고객사 고유 이름은 빼고 적어 주세요.

[Answer]: 운영 중 알림이 오면 Teams로 들어온 Datadog·CloudWatch 알림을 확인하고, Pod나 서비스 관련 알림이면 kubectl로 Pod 상태와 로그를 하나씩 조회해 1차 원인을 찾았다. AWS DevOps Agent로 알람 원인 분석을 해 보기도 했는데, 이 1차 분석을 쿠버네티스 환경에서 에이전트가 먼저 하게 직접 만들고, 그 정확도를 재 보고 싶었다.

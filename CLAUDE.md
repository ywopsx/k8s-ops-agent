# CLAUDE.md

작업을 시작하기 전에 `aidlc-docs/00-context.md`를 읽고, 범위와 원칙을 따른다.
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

EKS 클러스터 운영 에이전트. 현재 구현된 것은 Unit 1 `preflight/`(노드 교체·업그레이드 사전 점검, 읽기 전용) 하나이고, Unit 2(알림 1차 분석 → Slack 스레드)는 예정 단계다. Python 3.10+.

디렉터리 역할과 의존성 (자세한 결정은 `aidlc-docs/00-context.md`의 "결정 사항"):

- `preflight/`: 결정적인 점검만 한다. 표준 라이브러리만 쓰고 LLM을 부르지 않는다(`dependencies = []` 유지).
- `rehearsal/`: drain 검증·업그레이드 리허설처럼 클러스터를 바꾸는 검증 코드. kind에서만 실행한다.
- `agent/`: LLM(Anthropic API) 공통 계층. Unit 1 조치 계획 초안, Unit 2 분석.
- `agent/`, `rehearsal/`, Unit 2 코드의 외부 패키지는 `pyproject.toml`의 `[project.optional-dependencies]`로 분리한다.

코드 주석, 리포트 메시지·조치 문구, 커밋 메시지, 문서는 모두 한국어로 쓴다.

## 명령어

```bash
python3 -m pytest -q                                   # 전체 테스트 (dev 의존성: pytest>=8)
python3 -m pytest tests/test_checks.py::test_cni_overwritten_settings_are_detected   # 단일 테스트

python3 -m preflight --target-version 1.33 --from-dir tests/fixtures/snapshot        # 클러스터 없이 픽스처로 실행
python3 -m preflight --target-version 1.33 --from-dir tests/fixtures/snapshot \
  --cni-baseline tests/fixtures/cni-baseline.json --format json --fail-on never

./demo/run-demo.sh        # kind 클러스터(preflight-demo)에 문제를 심고 실행 → out/report.md, out/snapshot/
kind delete cluster --name preflight-demo

python3 -m rehearsal drain --node <노드> --context kind-<이름> --timeout 60   # kind 노드를 실제로 drain → out/rehearsal/<시각>/
./demo/run-drain-demo.sh  # kind 클러스터(preflight-rehearsal, worker 2)에 문제를 심고 worker1을 drain
kind delete cluster --name preflight-rehearsal
```

`rehearsal/` 테스트는 `tests/rehearsal_fakes.py`의 가짜 kubectl(`FakeCluster`)과 가짜 시계(`FakeClock`)를 쓴다. 클러스터에 접속하지 않는다.

`.venv/`가 있으면 그 안의 python을 쓴다. 린터·포매터 설정은 없다.

## 구조와 데이터 흐름

`cli.main` → `collect`(Snapshot 생성) → `checks.run_all`(Finding 목록) → `report`(md/json) → `--fail-on` 기준으로 종료 코드.

- **Snapshot** (`models.py`): `kubectl get <kind> -o json`의 `items`를 복수형·소문자 kind 이름(`"deployments"`, `"poddisruptionbudgets"` 등)을 키로 담는다. `collect.from_cluster`는 `NAMESPACED`/`CLUSTER_SCOPED` 목록의 kind만 조회하고, 조회 실패한 kind는 경고 후 건너뛴다. `from_dir`/`save`는 `<kind>.json` 파일 단위로 읽고 쓴다 — 따라서 픽스처 파일 이름이 곧 kind 키다.
- **Check** (`checks.py`): `(Snapshot, Context) -> list[Finding]` 순수 함수. 클러스터 접근 없이 dict만 다루므로 테스트는 dict를 직접 만들어 넣는다(`tests/test_checks.py`의 `deployment()`, `node()`, `aws_node()` 헬퍼 참고).
- **Finding/Severity**: `Severity`는 `IntEnum`(INFO < MEDIUM < HIGH)이라 `--fail-on` 비교와 정렬에 그대로 쓰인다. `run_all`은 심각도 내림차순 → check 이름 → ref 순으로 정렬하고, `to_markdown`은 점검 항목별로 묶어 가장 심각한 그룹부터 출력한다.

### 점검 추가·수정 시 함께 바꿀 곳

1. `checks.py`에 함수 작성 후 `ALL_CHECKS`에 등록
2. `report.py`의 `CHECK_TITLES`에 제목 추가
3. 새 리소스 종류가 필요하면 `collect.py`의 `NAMESPACED`/`CLUSTER_SCOPED`에 추가
4. `README.md`의 점검 항목 표, 필요하면 `demo/planted-issues.yaml`과 README의 데모 기대 결과 표

### 동작상 주의할 점

- **시스템 네임스페이스 처리가 점검마다 다르다.** `_skip_ns`로 kube-system 등을 기본 제외하지만(`--include-system`으로 포함), `nodegroup-pinned`는 의도적으로 제외하지 않는다(플랫폼 Pod가 노드그룹에 묶여 있던 실제 장애 사례, `test_platform_pods_in_kube_system_are_still_checked`). `vpc-cni-env`는 애초에 kube-system의 `aws-node`를 본다.
- **`removed-api`는 `kubectl.kubernetes.io/last-applied-configuration` 어노테이션의 apiVersion을 본다.** API 서버는 저장된 객체를 현재 버전으로 변환해 돌려주기 때문에 조회 결과의 apiVersion으로는 판단할 수 없다. Helm 등 어노테이션이 없는 리소스는 검출되지 않는다(알려진 한계). 데모에서 `kubectl create`가 이 흔적을 v1로 덮어써서, `run-demo.sh`는 생성 후 `kubectl patch`로 어노테이션을 넣는다 — 이 순서를 바꾸지 말 것.
- **`removed_apis.py`의 `REMOVED_APIS`는 수동 관리 표**다. 공식 Deprecated API Migration Guide와 대조해 갱신한다.
- `al2-node`는 대상 버전 1.33 이상에서 HIGH, 그 미만에서 MEDIUM. `vpc-cni-env`는 기준값과 다른 항목마다 HIGH, 그리고 현재 설정 스냅샷을 항상 INFO 하나로 남긴다.
- kind에는 AL2 노드와 aws-node가 없으므로 `al2-node`, `vpc-cni-env`는 `tests/fixtures/snapshot`으로만 검증된다. `test_cli.py`는 이 픽스처로 CLI 전체를 돌린다.

## 설계 원칙 (변경하지 말 것)

- **읽기 전용**: 클러스터에는 `kubectl get`만 실행한다. 수정·patch·delete를 하는 코드를 `preflight/`에 넣지 않는다.
- **자동 수정 금지**: 위험과 조치 방법(`hint`)을 보여 줄 뿐 고치지 않는다. 결정은 사람이 한다.
- **근거 보존**: `--save-snapshot`으로 점검 시점 리소스를 저장해 재현·전후 비교가 가능해야 한다.
- **CI 친화**: `--fail-on` 기준 이상의 Finding이 있으면 종료 코드 1.

## 공개 저장소 관련

- 조치 문구·테스트·픽스처에 실제 운영 환경의 이름(노드 라벨, 클러스터명 등)을 넣지 않는다. 일반 예시(`node-role: app`)를 쓴다.
- `docs/AI_USAGE.md`는 AI가 만든 결과를 사람이 어떻게 검증했는지 기록하는 문서다. 검증 중 바로잡은 내용이 생기면 날짜와 함께 표에 추가한다.

## 작업 규칙

- 점검 도구(`preflight/`)는 읽기 전용이다. 클러스터를 바꾸는 명령(apply, delete, patch 등)을 점검 코드에 넣지 않는다. 데모 스크립트(`demo/`)와 검증 코드(`rehearsal/`)만 예외다.
- `rehearsal/` 코드는 실행 전에 현재 컨텍스트가 `kind-`로 시작하는지 코드에서 확인하고, 아니면 아무것도 하지 않고 멈춘다.
- kubectl은 kind 클러스터(`kind-*` 컨텍스트)에서만 실행한다. 실행 전에 `kubectl config current-context`로 확인한다.
- 회사나 고객사 환경 정보(실제 라벨 이름, IP, 계정 ID, 도메인, 내부 시스템 이름)를 코드, 테스트, 문서에 넣지 않는다. 예시는 일반적인 값(예: `node-role: app`)을 쓴다.
- 실제 환경 이름으로 보이는 값(노드그룹 이름, 클러스터명 등)을 발견해도 문서(`aidlc-docs/`, `docs/`, README 등)와 커밋 메시지에 그 값을 그대로 옮겨 적지 않는다. "실제 환경 이름으로 보이는 노드그룹 값"처럼 이름 없이 설명하고, 위치는 파일 경로로만 가리킨다.
- 비밀 정보(kubeconfig, 토큰, `.env`)를 읽거나 커밋하지 않는다. Anthropic API 키는 환경 변수로만 읽고, 코드·문서·테스트·픽스처에 넣지 않는다. 테스트는 API를 부르지 않도록 가짜 클라이언트를 쓴다.
- Python은 `.venv` 가상 환경을 쓴다. 코드를 바꾸면 `python3 -m pytest -q`로 확인하고, 클러스터 동작에 영향이 있으면 `./demo/run-demo.sh` 결과도 확인한다.
- 큰 변경은 먼저 계획을 제안하고, 승인을 받은 뒤 진행한다.
- 커밋과 push는 사용자가 직접 한다.
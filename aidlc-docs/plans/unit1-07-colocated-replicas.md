# Unit 1 백로그 7번 — replica 한 노드 몰림 점검 계획

- **상태**: 완료 — 단위 테스트 75개 통과, kind 데모 두 개(`run-demo.sh`, `run-drain-demo.sh`) 확인 (2026-11-03)
- **작성일**: 2026-11-03
- **위치**: `preflight/` (읽기 전용 점검, 표준 라이브러리만)

## 배경

drain 데모(2026-11-03, `out/rehearsal/20261103-000339/`)에서 `order-api`(replica 2, PDB 없음)가 "예측 못 함·발생"으로 나왔다.

| Pod | evict 완료 (drain 시작 기준) | 대체 Pod Ready까지 | 다운타임 가능 |
| --- | --- | --- | --- |
| `order-api-…-2ljkg` | 2.6초 | 6.5초 | |
| `order-api-…-rf72h` | 2.8초 | 6.2초 | 예 |

두 Pod가 모두 worker1에 있었고, PDB가 없어서 두 번째 Pod가 첫 번째 대체 Pod보다 먼저 evict됐다. 그 사이 Ready Pod가 0개였다. 지금의 `single-replica`는 replica 1개만 보고 `pdb-blocks-drain`은 PDB가 있는 경우만 봐서, 이 경우를 둘 다 놓친다.

PDB가 하나라도 있으면(예: maxUnavailable 1) 두 번째 eviction은 첫 번째 대체 Pod가 Ready가 될 때까지 429로 막혀서 이런 일이 생기지 않는다. 그래서 "PDB 없음"을 조건에 넣는다.

## 1. 정할 것 (추천안 먼저)

### ① 점검 이름 — `colocated-replicas` (추천)

- 대안: `replicas-same-node`

[결정]: 추천안 채택 — `colocated-replicas` (2026-11-03)

### ② 심각도 — MEDIUM (추천)

- 이유: 결과(잠깐의 다운타임)가 `single-replica`와 같다. drain을 멈추게 하는 `pdb-blocks-drain`(HIGH)보다는 낮다.
- 대안: HIGH. replica를 2개로 늘려 안심하고 있던 서비스라 영향이 더 클 수 있다.

[결정]: 추천안 채택 — MEDIUM (2026-11-03)

### ③ 판정 조건 (추천)

다음을 모두 만족하면 Finding 하나를 낸다.

1. Deployment·StatefulSet의 `spec.replicas` ≥ 2 (`single-replica`와 같은 대상 종류)
2. 같은 네임스페이스에서 워크로드의 Pod를 selector로 고르는 PDB가 없음
3. 워크로드의 selector에 맞는 Pod 중 Ready(`status.conditions`의 `Ready=True`)이고 `spec.nodeName`이 있는 것이 2개 이상
4. 그 Ready Pod가 모두 같은 노드에 있음

- Pod와 워크로드를 잇는 방법: 워크로드의 `spec.selector`를 Pod 라벨과 맞춘다(추천). ReplicaSet을 수집하지 않아도 되고, PDB를 고르는 방식과 같다. 대안은 `replicasets`를 수집해 ownerReferences(Pod → ReplicaSet → Deployment)를 따라가는 것인데, 수집 대상이 늘어난다.
- "모든 Ready Pod"가 아니라 "한 노드가 빠지면 남는 Ready Pod가 0"으로 넓히는 일반화(예: replica 3 중 3개 몰림)는 조건 4와 같다. "남는 Pod가 너무 적음"(3 중 2개 몰림)은 다운타임이 아니라 용량 문제라 이번에 넣지 않는다.

[결정]: 추천안 채택 + 보완 (2026-11-03)

- 보완 1: PDB가 있어도 보호 효과가 없으면 "PDB 없음"과 같이 검출한다. 조건 2를 "Pod를 고르는 PDB 중 보호 효과가 있는 것이 없음"으로 바꾼다.
  - 보호 효과 없음: `maxUnavailable`이 replica 수 이상(퍼센트는 올림해서 계산, `100%` 포함), 또는 `minAvailable`이 `0`·`0%`
  - 그 밖의 값(`minAvailable: 1`, `maxUnavailable: 1` 등)은 두 번째 eviction을 첫 대체 Pod가 Ready가 될 때까지 막으므로 보호로 본다. 값을 해석할 수 없거나 둘 다 없는 PDB도 보호로 본다(추측으로 검출하지 않음).
- 보완 2: Ready Pod가 같은 AZ에 몰린 경우는 이번 범위에서 뺀다. 아래 "백로그 후보"에 적는다.

### ④ 노드가 하나뿐인 클러스터 — 그대로 보고 (추천)

- `preflight-demo`처럼 스케줄 가능한 노드가 하나면 replica 2개 이상 워크로드는 모두 이 조건에 걸린다. 실제로 drain하면 다운타임이 생기는 상황이라 그대로 보고한다.
- 영향: `./demo/run-demo.sh` 결과에 `order-api`, `zone-spread`(둘 다 replica 2, PDB 없음)가 새로 나온다. README의 데모 기대 결과 표를 고친다.
- 대안: 스케줄 가능한 노드가 하나면 워크로드별 Finding 대신 INFO 하나만 낸다.

[결정]: 추천안 채택 — 그대로 보고 (2026-11-03)

### ⑤ 시스템 네임스페이스 — `_skip_ns` 기본 제외 (추천)

- coredns(replica 2)처럼 kube-system에도 해당하는 워크로드가 많다. 다른 점검처럼 `--include-system`일 때만 본다.

[결정]: 추천안 채택 — 기본 제외 (2026-11-03)

## 2. 조치 문구 (초안)

- message: "Ready Pod {n}개가 모두 노드 {node}에 있고 PDB가 없습니다. 이 노드를 drain하면 대체 Pod가 뜨기 전에 모두 evict되어 서비스가 잠시 끊길 수 있습니다."
- hint: "PDB(maxUnavailable: 1 등)를 추가해 eviction이 하나씩 진행되게 하거나, `kubernetes.io/hostname` 기준 topologySpreadConstraints·podAntiAffinity로 Pod를 여러 노드에 나누세요."
- 점검 시점의 배치를 본다는 점을 message나 README에 밝힌다. 스케줄러가 나중에 다르게 배치할 수 있어서, 구조적인 조치(PDB, 분산 제약)를 hint로 준다.

## 3. 바꿀 곳 (CLAUDE.md "점검 추가·수정 시 함께 바꿀 곳")

| 파일 | 내용 |
| --- | --- |
| `preflight/checks.py` | `check_colocated_replicas` 작성, `ALL_CHECKS`에 등록. `selector_matches`를 `rehearsal/compare.py`에서 `preflight/`로 옮김(`preflight/` → `rehearsal/` 의존을 만들지 않기 위해) |
| `rehearsal/compare.py` | `selector_matches`를 `preflight`에서 import. `DRAIN_CHECKS`에 추가, `CHECK_PREDICTS`에 `"colocated-replicas": P_DOWNTIME` 추가 |
| `preflight/report.py` | `CHECK_TITLES`에 제목 추가 |
| `preflight/collect.py` | 변경 없음 (`pods`, `deployments`, `statefulsets`, `poddisruptionbudgets`는 이미 수집) |
| `tests/test_checks.py` | 아래 테스트 |
| `tests/fixtures/snapshot/` | 필요하면 `pods.json`에 몰린 Pod 예시 추가 (`test_cli.py` 기대값 확인) |
| `README.md` | 점검 항목 표, `run-demo.sh` 기대 결과 표(④), drain 데모 표의 `order-api`를 "예측함·발생"으로, 한계(점검 시점 배치 기준, AZ 몰림 제외) |

## 4. 테스트 (클러스터 없이)

- replica 2, PDB 없음, Ready Pod 2개가 같은 노드 → 검출
- 같은 조건에서 PDB가 selector로 Pod를 고름 → 검출 안 함
- Ready Pod가 다른 노드에 나뉨 → 검출 안 함
- Ready Pod 1개 + NotReady·Pending Pod 1개 → 검출 안 함 (Ready 2개 미만. 이 경우는 이미 다운타임에 가까워 별도 판단)
- replica 1 → 검출 안 함 (`single-replica`가 다룸)
- 보호 효과 없는 PDB → 검출: `maxUnavailable: 2`(replica 2), `maxUnavailable: "100%"`, `minAvailable: 0`
- 보호 효과 있는 PDB → 검출 안 함: `maxUnavailable: 1`, `maxUnavailable: "50%"`(replica 2 → 1), `minAvailable: 1`
- StatefulSet도 검출
- kube-system은 기본 제외, `--include-system`이면 검출
- `rehearsal` 비교: `order-api` 같은 결과가 "예측함·발생"으로 바뀌는지 (`tests/test_rehearsal_report.py`)

## 5. 백로그 후보 (이번 범위 밖)

- 같은 AZ 몰림: Ready Pod가 모두 같은 AZ(`topology.kubernetes.io/zone`)의 노드에 있는 워크로드. AZ 장애나 한 AZ의 노드를 한꺼번에 교체할 때 같은 문제가 생긴다. 노드 라벨로 AZ를 알아야 하고, 노드가 여러 AZ에 있는 클러스터에서만 의미가 있어서 따로 다룬다.

## 6. 완료 기준

- `python3 -m pytest -q` 통과
- `./demo/run-drain-demo.sh`에서 `order-api`의 다운타임 가능이 "예측함·발생"으로 나옴
- `./demo/run-demo.sh` 결과가 고친 README 기대 결과 표와 맞음

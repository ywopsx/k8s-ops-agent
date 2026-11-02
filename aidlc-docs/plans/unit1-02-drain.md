# Unit 1 백로그 2번 — drain 검증 구현 계획

- **상태**: 승인됨, 구현 중 (2026-11-02)
- **작성일**: 2026-11-02
- **위치**: `rehearsal/` (클러스터를 바꾸는 검증 코드, kind에서만 실행)

## 목표

kind 노드를 실제로 cordon·drain해서 Pod별 결과(막힘, 재배치, 걸린 시간)를 리포트로 남긴다. 같은 시점의 preflight 예측과 나란히 비교해 백로그 3번(업그레이드 리허설)의 기반으로 쓴다.

---

## 1. 정할 것 (추천안 먼저)

### ① drain 방식 — 직접 eviction 루프 (추천)

- 방식: `kubectl cordon` 후 노드의 Pod를 조회하고, Pod마다 Eviction API(`kubectl create --raw /api/v1/namespaces/<ns>/pods/<name>/eviction`)를 호출한다.
- 추천 이유: Pod별 결과와 시간을 정확히 얻을 수 있다. `kubectl drain`도 내부적으로 같은 일(cordon + eviction 반복)을 한다.
- 대안: `kubectl drain --timeout`을 감싸고 출력 문구를 파싱한다. 구현은 간단하지만 Pod별 시간 측정이 어렵고, kubectl 버전에 따라 문구가 바뀌면 깨진다.

[결정]: 추천안 채택 — 직접 eviction 루프 (2026-11-02)

### ② 클러스터 — drain 전용 kind 클러스터를 따로 만든다 (추천)

- 구성: `preflight-rehearsal` 클러스터, control-plane 1 + worker 2
- 이유: `preflight-demo`는 노드가 하나라 drain하면 Pod가 옮겨 갈 곳이 없다. 기존 데모와 README의 기대 결과 표는 그대로 둔다.
- 메모리: 노트북 RAM 8GB에서는 `preflight-demo`를 먼저 지우고 돌리라고 README에 적는다. 스크립트가 클러스터를 자동으로 지우지는 않는다.

[결정]: 추천안 채택 — drain 전용 클러스터 `preflight-rehearsal`, control-plane 1 + worker 2 (2026-11-02)

### ③ 단독 Pod — `--force` 없음 (추천)

컨트롤러 없는 Pod는 evict하지 않고 "막힘(컨트롤러 없음)"으로 기록한다. 자동 수정 금지 원칙과 같은 맥락이다.

[결정]: 추천안 채택 — `--force` 없음 (2026-11-02)

### ④ 끝난 뒤 정리 — 항상 uncordon (추천)

- 정상 종료, 타임아웃, Ctrl-C 모두 `finally`에서 uncordon한다.
- 조사용으로 노드를 cordon 상태로 남기려면 `--keep-cordoned` 옵션을 쓴다.
- 막힌 Pod는 타임아웃(기본 120초) 이후 더 시도하지 않는다.

[결정]: 추천안 채택 — 항상 uncordon, `--keep-cordoned`로만 유지 (2026-11-02)

### ⑤ 데모 노드그룹 값 교체

`demo/planted-issues.yaml`, 테스트, 픽스처에 실제 환경 이름으로 보이는 노드그룹 값이 남아 있다. 이번 작업에서 `ng-legacy` 같은 일반 값으로 바꾼다.

[결정]: 추천안 채택 — `ng-legacy`로 교체 (2026-11-02 완료, 커밋 36ff5d5)

### ⑥ 권한 설정

`.claude/settings.json`의 `ask`에 `kubectl cordon *`, `kubectl uncordon *`, `kubectl create --raw *`를 넣을지 정한다.

[결정]: `ask`에 `kubectl cordon *`, `kubectl uncordon *`, `kubectl create --raw *`, `python3 -m rehearsal *`, `./demo/*.sh` 추가 (2026-11-02)

---

### 추가 요구사항 (승인 시 사용자 지시)

- eviction이 500(한 Pod에 PDB가 여러 개)으로 거부될 때도 PDB 관련 막힘으로 분류하고 테스트에 넣는다.
- 리포트의 "PDB에 막힘" 설명에 EKS 관리형 노드그룹 업그레이드 기준을 적는다: Pod가 15분 안에 빠져나가지 않으면(force 플래그 없이) `PodEvictionFailure`로 실패한다. 공식 문서 확인 후 반영 — Amazon EKS 사용자 가이드 "Understand each phase of node updates"(https://docs.aws.amazon.com/eks/latest/userguide/managed-node-update-behavior.html). 이 문서는 알려진 원인으로 지나치게 엄격한 PDB와 한 Pod를 가리키는 PDB가 여러 개인 경우를 든다.

---

## 2. 안전장치 (`rehearsal/guard.py`)

1. 시작할 때 `kubectl config current-context`를 읽고, `kind-`로 시작하지 않으면 다른 kubectl 명령을 하나도 실행하지 않고 종료 코드 2로 멈춘다.
2. `--context`를 주면 그 값도 `kind-`로 시작해야 한다.
3. 이후 모든 kubectl 호출에 `--context <확인한 값>`을 붙인다. 실행 중 다른 터미널에서 컨텍스트를 바꿔도 다른 클러스터로 넘어가지 않게 하기 위해서다.
4. 대상 노드가 그 클러스터에 실제로 있는지 확인한 뒤에 cordon한다.

## 3. 동작 흐름

```
guard 확인
  → preflight 수집·점검 (예측, 스냅샷 저장)
  → cordon
  → 노드의 Pod 분류
       DaemonSet·mirror Pod → 건너뜀
       컨트롤러 없음        → 막힘
       나머지               → evict 대상
  → Pod별 eviction 반복 (429 = PDB에 막힘 → 재시도, 타임아웃까지)
  → evict된 Pod의 대체 Pod가 Ready가 되는지 대기 (Pending이면 스케줄 실패 Event 기록)
  → uncordon → 리포트
```

### Pod별 결과 분류

| 결과 | 판정 기준 | 대응하는 preflight 예측 |
| --- | --- | --- |
| 재배치 완료 | evict 성공, 대체 Pod Ready | — |
| 재배치 실패 | evict 성공, 대체 Pod가 Pending (스케줄 실패 Event 기록) | `nodegroup-pinned`, `topology-spread` |
| PDB에 막힘 | 타임아웃까지 eviction이 429 | `pdb-blocks-drain` |
| 컨트롤러 없음 | 단독 Pod라 evict하지 않음 | `unmanaged-pod` |
| 건너뜀 | DaemonSet, mirror Pod | — |

### 측정하는 시간 (Pod별 + 노드 전체)

- evict 요청부터 성공까지
- 기존 Pod가 Ready를 잃은 시점부터 대체 Pod가 Ready가 될 때까지 (`single-replica` 다운타임의 실측값)
- 노드 drain 전체 소요 시간

### 예측과 실측 비교

Pod를 ownerReferences(ReplicaSet → Deployment)로 따라가 워크로드 단위 ref로 묶는다. 그 뒤 preflight Finding과 맞춰 "예측함·실제 발생 / 예측함·발생 안 함 / 예측 못 함·발생" 표를 만든다.

## 4. 파일 구성

| 파일 | 역할 |
| --- | --- |
| `rehearsal/__init__.py`, `__main__.py`, `cli.py` | `python3 -m rehearsal drain --node <name> [--context] [--timeout 120] [--keep-cordoned] [--out out/rehearsal]` |
| `rehearsal/guard.py` | 컨텍스트 확인 |
| `rehearsal/kube.py` | kubectl 실행 함수. 읽기(get)와 쓰기(cordon·eviction·uncordon)를 나누고, 테스트에서 가짜 실행기로 바꿀 수 있게 함 |
| `rehearsal/drain.py` | 분류, eviction 반복, 대기, 결과 모델(`DrainResult`, `PodOutcome`) |
| `rehearsal/compare.py` | preflight 예측과 실측을 워크로드 단위로 맞춤 (구현 중 report.py에서 분리) |
| `rehearsal/report.py` | Markdown·JSON 리포트, 예측 비교 표 |
| `rehearsal/kind-config.yaml` | control-plane 1 + worker 2, worker에 zone 라벨 |
| `demo/run-drain-demo.sh` | 클러스터 생성 → 시나리오 배치 → `python3 -m rehearsal drain` 실행 |
| `tests/test_rehearsal_*.py` | 가짜 kubectl로 단위 테스트 |

- 의존성은 표준 라이브러리만 쓴다(외부 패키지 불필요).
- `rehearsal/`은 `preflight`의 collect·checks를 불러 쓴다. 반대 방향 의존(`preflight/` → `rehearsal/`)은 만들지 않는다.
- 결과 파일: `out/rehearsal/<시각>/drain-<node>.{md,json}`, drain 직전 스냅샷 `out/rehearsal/<시각>/snapshot/` (구현 중 한 실행의 결과를 한 디렉터리로 모음)

## 5. 데모 시나리오 (`demo/run-drain-demo.sh`)

1. 배치: worker2를 잠시 cordon하고 `planted-issues.yaml`을 적용한다. 모든 Pod가 worker1에 올라간다. 끝나면 worker2를 uncordon한다.
2. 실제 장애 재현: worker1에만 `legacy-batch`가 쓰는 노드그룹 라벨을 붙인다. worker1을 drain하면 대체 Pod가 갈 노드가 없어 Pending이 된다. AL2 → AL2023 노드그룹 전환 때 겪은 장애 그대로다.
3. 기대 결과

   | 워크로드 | 기대 결과 |
   | --- | --- |
   | `payment` | PDB에 막힘 |
   | `debug-shell` | 컨트롤러 없음 |
   | `legacy-batch` | 재배치 실패 (Pending) |
   | `order-api`, `zone-spread` | 재배치 완료 + 걸린 시간 |

## 6. 테스트 (클러스터 없이)

- guard: 컨텍스트가 `kind-`가 아니면 `config current-context` 외에 kubectl 호출이 하나도 없는지. `--context`가 kind가 아니면 거부하는지.
- 분류: DaemonSet, mirror, 단독 Pod, ReplicaSet 소유 Pod
- eviction: 429가 반복되다 타임아웃되면 PDB에 막힘, 201이면 대기 단계로, 404(이미 사라짐)는 성공으로 처리
- 정리: 예외가 나도 uncordon이 호출되는지, `--keep-cordoned`이면 호출되지 않는지
- 비교 표: preflight Finding과 실측 결과를 맞추는 로직
- 시간: 시계 함수를 주입해 결정적으로 테스트

## 7. 함께 고칠 문서

- `CLAUDE.md`: 명령어 절에 rehearsal 실행 명령 추가
- `README.md`: drain 검증 절, 메모리 안내, 한계(kind에는 실제 LB 대상 그룹 해제·Karpenter 통합이 없음)
- `aidlc-docs/00-context.md`: 진행 기록
- `aidlc-docs/audit.md`: 감사 기록

## 8. 완료 기준

- `python3 -m pytest -q` 통과
- `demo/run-drain-demo.sh`의 결과가 5장의 기대 결과 표와 맞음
- kind가 아닌 컨텍스트에서 실행하면 아무것도 바꾸지 않고 종료 코드 2로 멈춤

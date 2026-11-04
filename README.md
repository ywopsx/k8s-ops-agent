# k8s-ops-agent

EKS 클러스터를 운영하면서 반복하던 판단을 에이전트가 먼저 분석하고, 사람은 검토하고 승인하는 **클러스터 운영 에이전트**입니다.

| 구성 | 하는 일 | 상태 |
| --- | --- | --- |
| Unit 1. 노드 교체 사전 점검 (`preflight/`) | 업그레이드나 노드 교체를 실패하게 만드는 요소를 미리 찾는 읽기 전용 점검 | v0.1 |
| Unit 1. drain 검증 (`rehearsal/`) | kind 노드를 실제로 drain해 점검의 예측과 실제 결과를 비교 | 구현 |
| Unit 2. 알림 1차 분석 (`agent/`) | 알림 파일을 받아 읽기 전용 MCP 도구로 Pod 상태·Event·로그를 조회하고, 원인 후보·근거·런북을 리포트로 남김. 정답 원인 ID로 정확도 평가 | MVP |

---

## Unit 1. 노드 교체 사전 점검

Kubernetes(EKS) 클러스터를 업그레이드하기 전에, **업그레이드나 노드 교체를 실패하게 만드는 요소를 미리 찾아 주는 읽기 전용 점검 도구**입니다.

## 왜 만들었나

운영 중인 EKS 클러스터를 매 버전 직접 업그레이드하면서, 매번 같은 항목을 손으로 확인했습니다. 그리고 확인을 놓친 항목은 실제 장애로 이어졌습니다.

- **노드그룹 이름에 묶인 nodeSelector:** AL2 → AL2023 노드그룹 전환 때, Pod의 nodeSelector가 `eks.amazonaws.com/nodegroup`에 묶여 있어 새 노드그룹으로 옮길 수 없었습니다. 공용 역할 라벨로 바꾸는 작업을 먼저 해야 했습니다.
- **VPC CNI 설정 덮어쓰기:** vpc-cni add-on 업데이트로 aws-node의 Custom Networking 설정이 기본값으로 덮어써져, 신규 Pod가 IP를 받지 못했습니다.
- **제거되는 API, AL2 AMI 지원 종료:** 1.32 업그레이드 전에는 flowcontrol v1beta3 사용 여부를 kubectl과 jq로 하나씩 확인했습니다.

이 도구는 그 체크리스트를 코드로 옮긴 것입니다. 사람이 기억에 의존하던 확인을 반복 가능한 점검으로 바꾸는 것이 목표입니다.

## 점검 항목

| 점검 | 심각도 | 찾는 것 |
| --- | --- | --- |
| `nodegroup-pinned` | HIGH | nodeSelector·nodeAffinity가 노드그룹 이름 라벨에 묶인 워크로드 (kube-system 포함) |
| `pdb-blocks-drain` | HIGH | 허용된 중단 수가 0이거나 maxUnavailable이 0인 PDB |
| `removed-api` | HIGH | 대상 버전에서 제거된 apiVersion으로 apply된 리소스 |
| `al2-node` | HIGH (1.33+) | Amazon Linux 2 노드 |
| `vpc-cni-env` | HIGH / INFO | aws-node 환경변수가 기준값과 다른 경우, 그리고 현재 값 스냅샷 |
| `unmanaged-pod` | MEDIUM | 컨트롤러 없이 떠 있는 Pod (노드 교체 시 사라짐) |
| `single-replica` | MEDIUM | replica 1개 Deployment·StatefulSet (노드 교체 중 다운타임) |
| `lb-target-instance` | MEDIUM | target type이 instance인 ALB Ingress·NLB Service·TargetGroupBinding, in-tree CLB/NLB (Karpenter 전환 준비) |
| `topology-spread` | MEDIUM / INFO | AZ 분산 제약이 걸린 Deployment·StatefulSet. DoNotSchedule·필수 podAntiAffinity는 MEDIUM, ScheduleAnyway는 INFO |
| `colocated-replicas` | MEDIUM | replica 2개 이상인데 Ready Pod가 모두 한 노드에 있고, 보호 효과 있는 PDB가 없는 Deployment·StatefulSet (drain 때 대체 Pod보다 먼저 모두 evict됨). `maxUnavailable`이 replica 수 이상(100% 포함)이거나 `minAvailable`이 0인 PDB는 없는 것으로 봄 |

## 설계 원칙

1. **읽기 전용:** `kubectl get`만 실행하고 클러스터를 바꾸지 않습니다. 운영 클러스터에서도 부담 없이 돌릴 수 있어야 합니다.
2. **결정은 사람이:** 무엇이 왜 위험한지와 조치 방법을 리포트로 보여 줄 뿐, 자동으로 고치지 않습니다.
3. **근거를 남긴다:** `--save-snapshot`으로 점검 시점의 리소스를 저장해, 나중에 같은 결과를 재현하거나 업그레이드 전후를 비교할 수 있습니다.
4. **CI에서 쓸 수 있게:** 기준 심각도 이상이 있으면 종료 코드 1을 돌려줍니다(`--fail-on`).

## 사용법

```bash
# 현재 kubeconfig context의 클러스터를 1.33 기준으로 점검
python3 -m preflight --target-version 1.33

# 업그레이드 전 aws-node 설정을 기준값으로 저장해 두고, add-on 업데이트 후 비교
python3 -m preflight --target-version 1.33 --cni-baseline cni-baseline.json

# 클러스터 접속 없이, 저장해 둔 스냅샷으로 점검
python3 -m preflight --target-version 1.33 --from-dir out/snapshot

# JSON 출력, MEDIUM 이상이면 실패
python3 -m preflight --target-version 1.33 --format json --fail-on medium
```

`cni-baseline.json` 예시:

```json
{
  "AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG": "true",
  "ENABLE_PREFIX_DELEGATION": "true",
  "ENI_CONFIG_LABEL_DEF": "topology.kubernetes.io/zone"
}
```

## 검증

### 단위 테스트

```bash
pip install pytest
python3 -m pytest -q
```

실무에서 겪은 상황을 테스트로 재현합니다. 예를 들어 `test_cni_overwritten_settings_are_detected`는 add-on 업데이트로 Custom Networking 설정이 덮어써진 상태를, `test_platform_pods_in_kube_system_are_still_checked`는 kube-system의 플랫폼 Pod가 노드그룹 이름에 묶여 있던 상태를 재현합니다.

### kind 클러스터에서 실제로 확인

```bash
./demo/run-demo.sh
```

`demo/planted-issues.yaml`이 문제를 일부러 심어 둡니다. 결과에 아래 항목이 모두 나와야 합니다.

| 심어 둔 문제 | 기대 결과 |
| --- | --- |
| `legacy-batch`: 노드그룹 이름 nodeSelector, replica 1 | `nodegroup-pinned` HIGH, `single-replica` MEDIUM |
| `payment` + PDB `minAvailable: 1`, replica 1 | `pdb-blocks-drain` HIGH, `single-replica` MEDIUM |
| `debug-shell`: 단독 Pod | `unmanaged-pod` MEDIUM |
| `preflight-demo-legacy`: v1beta3로 apply한 흔적 | `removed-api` HIGH |
| `storefront-web`: ALB Ingress, target-type 미지정 | `lb-target-instance` MEDIUM |
| `storefront-nlb`: NLB Service, target type 미지정 | `lb-target-instance` MEDIUM |
| `zone-spread`: AZ 키 DoNotSchedule (노드에 zone 라벨을 붙여 정상 실행) | `topology-spread` MEDIUM, `colocated-replicas` MEDIUM |
| `order-api`: replica 2, PDB 없음 | `colocated-replicas` MEDIUM |

ip 모드 NLB Service `order-api`는 나오지 않아야 합니다. kind 데모 클러스터는 노드가 하나라, replica 2개이고 PDB가 없는 `order-api`·`zone-spread` Deployment는 Pod가 모두 같은 노드에 있어 `colocated-replicas`로 나옵니다(실제로 drain하면 다운타임이 생기는 상태). kube-system의 coredns도 같은 조건이지만 시스템 네임스페이스라 `--include-system` 없이는 나오지 않습니다. kind에는 AWS Load Balancer Controller가 없어 Ingress와 LoadBalancer Service는 실제 로드밸런서 없이 남지만, 점검은 spec과 어노테이션만 봅니다. TargetGroupBinding은 CRD가 없어 kind에서는 조회되지 않으므로 `tests/fixtures/snapshot`으로 검증합니다. TargetGroupBinding처럼 설치되지 않을 수 있는 CRD만 리소스 종류가 없을 때 경고 없이 건너뜁니다. 기본 리소스(pods, nodes 등)를 조회하지 못하면 항상 경고합니다.

kind에는 AL2 노드와 aws-node가 없어서, `al2-node`와 `vpc-cni-env`는 `tests/fixtures/snapshot`으로 검증합니다. kind 기본 컴포넌트(예: `local-path-storage`의 provisioner)도 replica 1개로 나올 수 있는데, 이는 정상적인 결과입니다.

## drain 검증 (`rehearsal/`)

점검이 예측한 문제가 실제 drain에서도 일어나는지 kind에서 확인합니다. **클러스터를 실제로 바꾸는 코드라 kind에서만 실행합니다.** 현재 컨텍스트와 `--context`가 모두 `kind-`로 시작하지 않으면 다른 명령을 하나도 실행하지 않고 종료 코드 2로 멈추고, 이후 모든 kubectl 호출에 확인한 컨텍스트를 붙입니다.

```bash
python3 -m rehearsal drain --node <노드> [--context kind-...] [--timeout 120] [--keep-cordoned]
```

1. drain 직전 리소스를 스냅샷으로 저장하고, drain 관련 점검(`pdb-blocks-drain`, `unmanaged-pod`, `nodegroup-pinned`, `topology-spread`, `single-replica`, `colocated-replicas`)으로 예측합니다.
2. 노드를 cordon하고, Pod마다 Eviction API를 호출합니다(`kubectl drain`과 같은 방식). PDB에 막히면(429, 또는 PDB가 여러 개라 500) 타임아웃까지 다시 시도합니다. 컨트롤러 없는 Pod는 evict하지 않습니다(`--force`에 해당하는 삭제는 하지 않음).
3. evict된 Pod의 대체 Pod가 Ready가 되는지 기다리고, 걸린 시간과 스케줄 실패 메시지를 남깁니다.
4. 끝나면 항상 uncordon합니다(`--keep-cordoned` 제외, Ctrl-C나 오류에도).
5. `out/rehearsal/<시각>/`에 `drain-<노드>.md`, `drain-<노드>.json`, `snapshot/`을 남깁니다. 막히거나 재배치에 실패한 Pod가 있으면 종료 코드 1입니다.

리포트에는 Pod별 결과(재배치 완료·재배치 실패·PDB에 막힘·컨트롤러 없음·evict 실패·건너뜀), 걸린 시간, 다운타임 가능 여부(evict 시점에 같은 워크로드의 다른 Ready Pod가 없었는지)와 함께, 예측과 실측을 워크로드 단위로 맞춘 표(예측함·발생 / 예측함·발생 안 함 / 예측 못 함·발생)가 들어갑니다. PDB에 막힌 Pod가 있으면 EKS 관리형 노드그룹 업그레이드가 15분 동안 evict하지 못하면 `PodEvictionFailure`로 실패한다는 기준([공식 문서](https://docs.aws.amazon.com/eks/latest/userguide/managed-node-update-behavior.html))을 함께 적습니다.

### 데모

```bash
./demo/run-drain-demo.sh      # kind 클러스터 preflight-rehearsal (control-plane 1 + worker 2)
kind delete cluster --name preflight-rehearsal
```

노트북 메모리가 작으면 `preflight-demo` 클러스터를 먼저 지우세요. 스크립트는 worker2를 잠시 cordon한 채 `demo/planted-issues.yaml`을 적용해 문제 워크로드를 worker1에 모은 뒤, worker1을 60초 타임아웃으로 drain합니다. worker1에만 노드그룹 라벨(`ng-legacy`)과 zone-a, worker2에는 zone-b 라벨을 붙입니다.

| 워크로드 | 기대 결과 | 예측과 비교 |
| --- | --- | --- |
| `payment` (replica 1 + PDB) | PDB에 막힘 | `pdb-blocks-drain` 예측함·발생, `single-replica` 예측함·발생 안 함 (evict되지 않았으므로) |
| `legacy-batch` (노드그룹 라벨) | 재배치 실패 — 대체 Pod Pending | `nodegroup-pinned` 예측함·발생, `single-replica` 예측함·발생 |
| `zone-spread` (zone DoNotSchedule) | worker1의 Pod 재배치 실패 — zone-b로만 갈 수 있어 maxSkew 위반 | `topology-spread` 예측함·발생 |
| `debug-shell` | 컨트롤러 없음 | `unmanaged-pod` 예측함·발생 |
| `order-api` (replica 2, PDB 없음) | 재배치 완료, 두 번째 Pod는 다운타임 가능 | `colocated-replicas` 예측함·발생 — 두 replica가 한 노드에 몰려 있어 대체 Pod가 뜨기 전에 모두 evict됨 |

kind 시스템 Pod(coredns, local-path-provisioner 등)가 worker1에 있었다면 함께 evict되어 표에 나옵니다. 시스템 네임스페이스는 `--include-system`을 주지 않으면 예측 비교에서 빠집니다.

---

## Unit 2. 알림 1차 분석 에이전트 (`agent/`)

알림이 오면 읽기 전용 도구로 클러스터를 조회해 **원인 후보와 근거, 런북, 확인 명령**을 리포트로 남기는 에이전트입니다. 조치는 하지 않습니다.

### 왜 만들었나

운영 중 알림(Datadog·CloudWatch)이 메신저로 들어오면, Pod나 서비스 관련 알림은 kubectl로 Pod 상태와 로그를 하나씩 조회해 1차 원인을 찾았습니다. 관리형 AI 분석 도구로 알람 원인 분석을 해 보기도 했는데, 이 1차 분석을 쿠버네티스 환경에서 에이전트가 먼저 하도록 직접 만들고 **정확도를 재 보는 것**이 목표입니다.

### 구조

```
알림 파일(Alertmanager webhook JSON)
  → agent (MCP 클라이언트, 에이전트 루프는 직접 구현)
      ├─ LLM 백엔드: claude -p (내장 도구 모두 끔)   ← 다음 행동을 JSON 텍스트로만 답함
      ├─ MCP 서버 1: kubernetes-mcp-server (read_only = true)
      └─ MCP 서버 2: preflight_mcp (run_preflight, Unit 1 점검)
  → out/agent/reports/<시각>-<알림>-<모드>.{md,json}
```

- **모드 C (기본):** Pod 상태와 Event만 먼저 수집해 LLM에 줍니다. LLM은 근거가 부족하면 읽기 도구(로그, Service, Endpoints 등)를 골라 추가 조회를 요청하고, 최대 5회까지 조회한 뒤 결론을 냅니다.
- **모드 A (비교용, `--mode a`):** 정해 둔 조회(Pod, 로그 현재·직전, Event, Service, Endpoints, Deployment)를 모두 한 뒤 LLM을 한 번만 부릅니다.
- LLM은 원인 후보를 정해진 원인 ID 목록(`agent/causes.py`, 정답 4개 + 헷갈리기 쉬운 원인 6개)에서만 골라 자동 채점할 수 있게 했습니다.
- 도구 결과는 LLM에 넘기기 전에 토큰·비밀번호·액세스 키·URL 사용자 정보·IP를 마스킹하고(`agent/mask.py`), 로그는 최근 50줄(`--log-lines`)만 보냅니다.
- 런북은 시나리오별로 `runbooks/`에 짧게 써 두고 프롬프트에 넣습니다. 리포트에는 1순위 원인의 런북을 붙입니다.

### 권한: 세 겹 + 허용 목록

| 겹 | 방법 | 확인한 것 |
| --- | --- | --- |
| 1. MCP 서버 | `kubernetes-mcp-server`를 `read_only = true`, `toolsets = ["core"]`로 실행 | 쓰기 도구 6개(`pods_delete`, `pods_exec`, `pods_run`, `resources_create_or_update`, `resources_delete`, `resources_scale`)가 도구 목록에서 빠짐 |
| 2. kubeconfig | 기본 `view` ClusterRole만 가진 ServiceAccount 토큰 (`demo/agent-viewer-kubeconfig.sh`) | `auth can-i`: list pods yes, get secrets no, delete pods no. MCP로 Secret을 조회하면 `forbidden` |
| 3. 컨텍스트 | 현재 컨텍스트가 `kind-`로 시작하지 않으면 MCP 서버를 띄우기 전에 멈춤 (`rehearsal.guard` 재사용, 종료 코드 2) | 테스트 `test_cli_stops_before_starting_mcp_when_not_kind` |
| + 허용 목록 | 서버가 내놓는 도구 중 읽기 도구 7개 + `run_preflight`만 LLM에 보여 줌 (`agent/tools.py`) | 목록에 없는 도구 요청은 실행하지 않고 호출 횟수로 셈 |

### LLM 백엔드: `claude -p`에서 내장 도구 막기

LLM은 텍스트(JSON)로 다음 행동만 답하고, 도구 실행은 에이전트 코드가 MCP로 합니다. `claude -p`를 아래 옵션으로 부릅니다(`agent/llm.py`).

```bash
claude -p --tools "" --strict-mcp-config --setting-sources "" --no-session-persistence \
  --output-format stream-json --verbose --system-prompt "<에이전트 프롬프트>" --model <모델>   # 프롬프트는 stdin, cwd는 빈 임시 디렉터리
```

- `--tools ""`: 내장 도구(Bash, 파일 읽기·쓰기 등)를 모두 끕니다(`claude --help`: *Use "" to disable all tools*).
- `--strict-mcp-config`: `--mcp-config`로 준 MCP 서버만 씁니다. 주지 않으므로 MCP 서버도 없습니다.
- `--setting-sources ""`, 빈 임시 cwd: 사용자·프로젝트 설정(hooks, 권한, MCP)과 프로젝트 CLAUDE.md를 읽지 않습니다. `--system-prompt`로 기본 시스템 프롬프트도 바꿉니다.
- **실제로 확인:** init 이벤트가 `tools: []`, `mcp_servers: []`였고, "Bash로 `echo hacked > proof.txt`를 실행하라"는 요청에 파일이 생기지 않았습니다.
- **매 호출 확인:** stream-json의 init 이벤트에서 `tools`·`mcp_servers`가 비어 있지 않으면 답을 버리고 멈춥니다(`ToolsNotDisabledError`).
- 토큰과 비용은 `claude -p` 결과의 `usage`·`total_cost_usd`에 있으면 기록하고, 없으면 시간만 기록합니다. `claude -p`는 프롬프트 캐시를 쓰므로 입력 토큰은 캐시 읽기·쓰기와 함께 봐야 합니다.
- 백엔드는 `Backend` 인터페이스(`complete(system, prompt)`)로 나눠 두어 Anthropic API 백엔드로 바꿀 수 있습니다. 테스트는 가짜 백엔드를 써서 실제 호출을 하지 않습니다.

### 사용법

```bash
pip install -e '.[agent]'      # mcp(SDK), kubernetes-mcp-server. preflight/는 계속 표준 라이브러리만 씁니다

./demo/run-agent-demo.sh            # kind 클러스터 ops-agent에 시나리오 4개 → 알림 파일 → 리포트 (모드 C)
./demo/run-agent-demo.sh --eval     # + 평가 (EVAL_MODEL, EVAL_REPEATS로 조정)
kind delete cluster --name ops-agent

python3 -m agent analyze --alert out/agent/alerts/order-sync-crashlooping.json [--mode a] [--model claude-sonnet-5-5]
python3 -m agent eval --repeats 3 --modes c,a --model claude-sonnet-5-5
```

| 시나리오 | 워크로드 (원인을 드러내지 않는 이름) | 알림 | 정답 원인 ID |
| --- | --- | --- | --- |
| A OOMKilled | `report-worker`: 메모리 limit 48Mi에서 256MB 버퍼를 잡음 | `KubePodCrashLooping` | `oom_killed` |
| B CrashLoopBackOff | `order-sync`: 필수 환경변수가 없어 시작 직후 종료 | `KubePodCrashLooping` | `app_config_error` |
| C Service selector 오류 | `checkout-api`: Pod는 Ready, Service selector가 Pod 라벨과 다름 | `ProbeFailed` (blackbox) | `service_selector_mismatch` |
| F Pod Pending | `batch-runner`: 클러스터에 없는 `node-role: batch` 노드 라벨에 묶임 | `KubePodNotReady` | `pending_node_selector_mismatch` |

A와 B는 같은 알림(`KubePodCrashLooping`)이라 알림 이름만으로는 구분할 수 없습니다. 컨테이너가 실행하는 스크립트는 ConfigMap에 두어, Pod spec의 command에 에러 문구가 그대로 보이지 않게 했습니다(처음에는 command에 문구가 있어 로그를 보지 않고도 맞히는 문제가 있었습니다).

### Claude Code에서 preflight MCP 서버 쓰기

```bash
claude mcp add preflight -e KUBECONFIG=$PWD/out/agent/kubeconfig-viewer -e PYTHONPATH=$PWD -- $PWD/.venv/bin/python -m preflight_mcp
```

Claude Code 대화에서 "1.33 업그레이드 전 사전 점검을 돌려 줘"라고 하면 `run_preflight` 도구를 부릅니다. 이 서버도 `kind-` 컨텍스트에서만 실행하고, preflight가 stdout에 찍는 조회 경고는 결과의 `warnings`로 돌려줍니다(stdio MCP에서 stdout은 JSON-RPC 통로라서).

### 평가

2026-11-04, kind 클러스터 하나에서 시나리오 4개를 동시에 띄운 상태로 측정했습니다. 주 모델 `claude-sonnet-5-5`는 시나리오 4 × 3회 × 모드 2 = 24회, 비교 모델 `claude-haiku-5-5`는 시나리오 4 × 1회 × 모드 2 = 8회 돌렸습니다. 1순위 원인 ID가 정답과 같으면 맞음으로 채점했습니다(`python3 -m agent eval`, 결과는 `out/agent/eval/<시각>-<모델>/summary.md`).

| 모델 | 모드 | 정확도 | 평균 시간(초) | 평균 도구 호출 (LLM 선택) | 평균 도구 호출 (전체) | 평균 LLM 호출 | 평균 입력 토큰* | 평균 출력 토큰 | 평균 비용(USD)** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude-sonnet-5-5 | C (기본) | **12/12** | 14.48 | 0.58 | 3.33 | 1.58 | 15,175 | 1,090 | 0.0503 |
| claude-sonnet-5-5 | A (고정 수집) | **12/12** | 10.55 | 0 | 7.25 | 1 | 9,329 | 1,024 | 0.0388 |
| claude-haiku-5-5 | C (기본) | 4/4 | 14.36 | 0.5 | 3.25 | 1.5 | 14,278 | 1,814 | 0.0029 |
| claude-haiku-5-5 | A (고정 수집) | 4/4 | 10.78 | 0 | 7.25 | 1 | 9,338 | 1,327 | 0.0022 |

\* 입력 + 캐시 읽기 + 캐시 쓰기. \*\* `claude -p`가 보고한 `total_cost_usd`. 주 모델 24회 합계 약 $1.07, 비교 모델 8회 합계 약 $0.02.

주 모델의 시나리오별 결과 (모드 C에서 LLM이 고른 추가 조회):

| 시나리오 | C 정확도 | C 평균 시간 | C 추가 조회 | A 정확도 | A 평균 시간 |
| --- | --- | --- | --- | --- | --- |
| A OOMKilled | 3/3 | 11.27초 | 0회 — Pod의 `lastState.terminated.reason: OOMKilled`로 충분 | 3/3 | 10.86초 |
| B CrashLoopBackOff | 3/3 | 20.68초 | 평균 1.33회 — 직전·현재 로그(`pods_log`)에서 `ORDER_DB_URL is not set` 확인 | 3/3 | 12.19초 |
| C Service selector | 3/3 | 15.27초 | 1회 — Service·Endpoints 조회로 selector와 Pod 라벨 비교 | 3/3 | 8.75초 |
| F Pod Pending | 3/3 | 10.72초 | 0회 — `FailedScheduling` Event 문구로 충분 | 3/3 | 10.4초 |

**읽는 법과 한계**

- **정확도는 32회 모두 맞았지만, 이 시나리오로는 변별력이 없습니다.** 원인이 하나이고 신호(종료 사유, 로그 문구, 빈 엔드포인트, 스케줄 실패 Event)가 분명한 장애라 두 모델·두 모드 모두 천장에 닿았습니다. 정확도 차이를 보려면 원인이 겹치거나 신호가 약한 시나리오(NetworkPolicy 차단, CoreDNS 장애, 설정은 맞지만 의존 서비스가 죽은 경우)가 필요합니다.
- **이번 4개 시나리오에서는 모드 A가 더 빠르고 쌌습니다.** 고정 수집(로그, Service, Endpoints, Deployment)이 4개 시나리오의 신호를 모두 담고 있어서, LLM을 한 번만 부르면 됐습니다. 모드 C는 Kubernetes 조회를 절반 이하로 줄였지만(3.33회 vs 7.25회), 추가 조회마다 LLM을 다시 부르면서 전체 맥락을 다시 보내 시간과 토큰이 늘었습니다. 모드 C는 고정 수집에 없는 정보가 필요한 장애에서 이점이 있을 것으로 보지만, 이번 평가로는 확인하지 못했습니다.
- **모드 C의 도구 선택은 시나리오에 맞았습니다.** 상태와 Event로 충분한 A·F에서는 추가 조회를 하지 않았고, 로그가 필요한 B에서는 `pods_log`를, 엔드포인트가 필요한 C에서는 Service·Endpoints를 골랐습니다. 5회 한도에 닿은 실행은 없었습니다.
- **비교 모델(Haiku)은 4/4로 같은 결과를 약 1/17 비용으로 냈습니다.** 다만 시나리오당 1회만 돌렸습니다.
- 시간에는 `claude -p` 프로세스 시작 시간이 포함됩니다(LLM 호출마다 새 프로세스).

### 한계와 확장

- **kind에서의 재현입니다.** 장애 4개가 한 네임스페이스에 동시에 떠 있어서, 분석마다 다른 장애 Pod도 함께 보입니다(실제 운영처럼 잡음이 있는 상태). 시나리오당 3회라 정확도 수치는 작은 표본입니다.
- **view 권한으로는 노드를 읽지 못합니다.** Pending 시나리오는 노드 라벨 대신 `FailedScheduling` Event 문구를 근거로 판단합니다. `run_preflight`도 노드·클러스터 범위 리소스 조회가 막혀 일부 점검이 경고와 함께 빠집니다.
- **지표·로그 저장소가 없습니다.** Prometheus·Loki 없이 Kubernetes API(Pod 상태, Event, 컨테이너 로그)만 봅니다.
- **확장 (설계 의도만, 붙이지 않음):** 실무에서는 Datadog MCP, GitLab MCP를 추가로 붙여 지표와 배포 이력까지 보도록 확장할 수 있습니다. 에이전트가 MCP 클라이언트라 서버와 허용 목록(`agent/tools.py`)만 늘리면 됩니다.

## 한계와 다음 단계

- **제거된 API 점검은 `kubectl apply` 이력에 의존합니다.** API 서버는 저장된 객체를 지원하는 버전으로 바꿔 돌려주기 때문에, `last-applied-configuration` 어노테이션이 없는 리소스(Helm으로 배포한 리소스 등)는 찾지 못합니다. 다음 단계로 `helm get manifest` 결과를 함께 점검할 계획입니다.
- **EKS add-on 호환성**(coredns, kube-proxy, vpc-cni의 대상 버전 지원 여부)은 AWS API(`aws eks describe-addon-versions`) 연동이 필요해 다음 단계로 남겨 두었습니다.
- **instance 모드 대상 그룹이 ASG에 직접 붙어 있는지는 알 수 없습니다.** 클러스터 밖(Terraform 등)에서 대상 그룹을 ASG에 붙인 경우 Karpenter 노드는 등록되지 않지만, 이는 AWS API로만 확인할 수 있습니다. 또 IngressClassParams나 Service 쪽 어노테이션으로 target type을 정한 경우는 반영하지 않습니다.
- **제거된 API 표**(`preflight/removed_apis.py`)는 새 버전이 나올 때마다 갱신해야 합니다.
- **`colocated-replicas`는 점검 시점의 Pod 배치를 봅니다.** 스케줄러가 나중에 다르게 배치할 수 있어서, 조치 문구는 PDB와 노드 분산 제약 같은 구조적인 방법을 안내합니다. Ready Pod가 같은 AZ에 몰린 경우(AZ 장애·한 AZ 노드 일괄 교체 때의 같은 문제)는 아직 보지 않습니다.
- **drain 검증은 kind에서의 재현입니다.** 실제 EKS의 로드밸런서 대상 해제(`exclude-from-external-load-balancers`), 새 노드 기동, Karpenter 통합은 일어나지 않습니다. eviction과 대체 Pod 대기는 하나의 타임아웃 안에서 진행하므로, 타임아웃 직전에 evict된 Pod는 대체 Pod를 기다릴 시간이 짧습니다. 다운타임 가능 여부는 evict 시점의 Ready Pod 수로 판단한 것이고, 실제 요청 실패를 측정한 것은 아닙니다.

## AI 활용

구현 과정에서 AI 코딩 에이전트를 어떻게 쓰고 무엇을 직접 검증했는지는 [docs/AI_USAGE.md](docs/AI_USAGE.md)에 기록했습니다.

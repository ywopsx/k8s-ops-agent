# k8s-ops-agent

EKS 클러스터를 운영하면서 반복하던 판단을 에이전트가 먼저 분석하고, 사람은 검토하고 승인하는 **클러스터 운영 에이전트**입니다.

| 구성 | 하는 일 | 상태 |
| --- | --- | --- |
| Unit 1. 노드 교체 사전 점검 (`preflight/`) | 업그레이드나 노드 교체를 실패하게 만드는 요소를 미리 찾는 읽기 전용 점검 | v0.1 |
| Unit 2. 알림 1차 분석 | 알림이 오면 상태를 조회하고 원인 후보와 런북을 Slack 스레드에 남김 | 예정 |

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

`demo/planted-issues.yaml`이 문제를 일부러 심어 둡니다. 결과에 아래 항목이 모두 나오고, 정상 워크로드(`order-api`)는 나오지 않아야 합니다.

| 심어 둔 문제 | 기대 결과 |
| --- | --- |
| `legacy-batch`: 노드그룹 이름 nodeSelector, replica 1 | `nodegroup-pinned` HIGH, `single-replica` MEDIUM |
| `payment` + PDB `minAvailable: 1`, replica 1 | `pdb-blocks-drain` HIGH, `single-replica` MEDIUM |
| `debug-shell`: 단독 Pod | `unmanaged-pod` MEDIUM |
| `preflight-demo-legacy`: v1beta3로 apply한 흔적 | `removed-api` HIGH |
| `storefront-web`: ALB Ingress, target-type 미지정 | `lb-target-instance` MEDIUM |
| `storefront-nlb`: NLB Service, target type 미지정 | `lb-target-instance` MEDIUM |
| `zone-spread`: AZ 키 DoNotSchedule (노드에 zone 라벨을 붙여 정상 실행) | `topology-spread` MEDIUM |

ip 모드 NLB Service `order-api`는 나오지 않아야 합니다. kind에는 AWS Load Balancer Controller가 없어 Ingress와 LoadBalancer Service는 실제 로드밸런서 없이 남지만, 점검은 spec과 어노테이션만 봅니다. TargetGroupBinding은 CRD가 없어 kind에서는 조회되지 않으므로 `tests/fixtures/snapshot`으로 검증합니다. TargetGroupBinding처럼 설치되지 않을 수 있는 CRD만 리소스 종류가 없을 때 경고 없이 건너뜁니다. 기본 리소스(pods, nodes 등)를 조회하지 못하면 항상 경고합니다.

kind에는 AL2 노드와 aws-node가 없어서, `al2-node`와 `vpc-cni-env`는 `tests/fixtures/snapshot`으로 검증합니다. kind 기본 컴포넌트(예: `local-path-storage`의 provisioner)도 replica 1개로 나올 수 있는데, 이는 정상적인 결과입니다.

## 한계와 다음 단계

- **제거된 API 점검은 `kubectl apply` 이력에 의존합니다.** API 서버는 저장된 객체를 지원하는 버전으로 바꿔 돌려주기 때문에, `last-applied-configuration` 어노테이션이 없는 리소스(Helm으로 배포한 리소스 등)는 찾지 못합니다. 다음 단계로 `helm get manifest` 결과를 함께 점검할 계획입니다.
- **EKS add-on 호환성**(coredns, kube-proxy, vpc-cni의 대상 버전 지원 여부)은 AWS API(`aws eks describe-addon-versions`) 연동이 필요해 다음 단계로 남겨 두었습니다.
- **instance 모드 대상 그룹이 ASG에 직접 붙어 있는지는 알 수 없습니다.** 클러스터 밖(Terraform 등)에서 대상 그룹을 ASG에 붙인 경우 Karpenter 노드는 등록되지 않지만, 이는 AWS API로만 확인할 수 있습니다. 또 IngressClassParams나 Service 쪽 어노테이션으로 target type을 정한 경우는 반영하지 않습니다.
- **제거된 API 표**(`preflight/removed_apis.py`)는 새 버전이 나올 때마다 갱신해야 합니다.

## AI 활용

구현 과정에서 AI 코딩 에이전트를 어떻게 쓰고 무엇을 직접 검증했는지는 [docs/AI_USAGE.md](docs/AI_USAGE.md)에 기록했습니다.

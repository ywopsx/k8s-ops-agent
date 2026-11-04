# Pod Pending — nodeSelector에 맞는 노드 없음

**확인할 것**
- Pod의 Event에 `FailedScheduling`과 "didn't match Pod's node affinity/selector"가 있는지 본다. "Insufficient cpu/memory"라면 리소스 부족 쪽이다.
- `kubectl -n <ns> get pod <pod> -o jsonpath='{.spec.nodeSelector}'`와 노드 라벨(`kubectl get nodes --show-labels`)을 비교한다.
- 노드그룹 교체·Karpenter 전환 뒤라면 노드그룹 이름 라벨처럼 사라진 라벨에 묶여 있지 않은지 본다 (Unit 1 `nodegroup-pinned` 점검과 같은 원인).

**조치 (사람이 결정)**
1. 워크로드의 nodeSelector를 실제로 있는 공용 역할 라벨로 바꾸거나, 해당 라벨을 가진 노드(노드그룹·NodePool)를 준비한다.
2. 노드 라벨을 손으로 붙이는 것은 임시 조치로만 쓴다.

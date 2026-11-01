"""Kubernetes 버전별로 제거된 API 목록.

출처: Kubernetes Deprecated API Migration Guide
(https://kubernetes.io/docs/reference/using-api/deprecation-guide/)
새 버전이 나오면 이 표에 항목을 추가한다.
"""

# (apiVersion, kind) -> 제거된 버전, 대체 apiVersion
REMOVED_APIS: dict[tuple[str, str], tuple[tuple[int, int], str]] = {
    ("extensions/v1beta1", "Ingress"): ((1, 22), "networking.k8s.io/v1"),
    ("networking.k8s.io/v1beta1", "Ingress"): ((1, 22), "networking.k8s.io/v1"),
    ("networking.k8s.io/v1beta1", "IngressClass"): ((1, 22), "networking.k8s.io/v1"),
    ("apiextensions.k8s.io/v1beta1", "CustomResourceDefinition"): ((1, 22), "apiextensions.k8s.io/v1"),
    ("rbac.authorization.k8s.io/v1beta1", "ClusterRole"): ((1, 22), "rbac.authorization.k8s.io/v1"),
    ("rbac.authorization.k8s.io/v1beta1", "ClusterRoleBinding"): ((1, 22), "rbac.authorization.k8s.io/v1"),
    ("rbac.authorization.k8s.io/v1beta1", "Role"): ((1, 22), "rbac.authorization.k8s.io/v1"),
    ("rbac.authorization.k8s.io/v1beta1", "RoleBinding"): ((1, 22), "rbac.authorization.k8s.io/v1"),
    ("batch/v1beta1", "CronJob"): ((1, 25), "batch/v1"),
    ("policy/v1beta1", "PodDisruptionBudget"): ((1, 25), "policy/v1"),
    ("policy/v1beta1", "PodSecurityPolicy"): ((1, 25), "제거됨 (Pod Security Admission으로 대체)"),
    ("autoscaling/v2beta1", "HorizontalPodAutoscaler"): ((1, 25), "autoscaling/v2"),
    ("discovery.k8s.io/v1beta1", "EndpointSlice"): ((1, 25), "discovery.k8s.io/v1"),
    ("autoscaling/v2beta2", "HorizontalPodAutoscaler"): ((1, 26), "autoscaling/v2"),
    ("flowcontrol.apiserver.k8s.io/v1beta1", "FlowSchema"): ((1, 26), "flowcontrol.apiserver.k8s.io/v1"),
    ("flowcontrol.apiserver.k8s.io/v1beta1", "PriorityLevelConfiguration"): ((1, 26), "flowcontrol.apiserver.k8s.io/v1"),
    ("storage.k8s.io/v1beta1", "CSIStorageCapacity"): ((1, 27), "storage.k8s.io/v1"),
    ("flowcontrol.apiserver.k8s.io/v1beta2", "FlowSchema"): ((1, 29), "flowcontrol.apiserver.k8s.io/v1"),
    ("flowcontrol.apiserver.k8s.io/v1beta2", "PriorityLevelConfiguration"): ((1, 29), "flowcontrol.apiserver.k8s.io/v1"),
    ("flowcontrol.apiserver.k8s.io/v1beta3", "FlowSchema"): ((1, 32), "flowcontrol.apiserver.k8s.io/v1"),
    ("flowcontrol.apiserver.k8s.io/v1beta3", "PriorityLevelConfiguration"): ((1, 32), "flowcontrol.apiserver.k8s.io/v1"),
}

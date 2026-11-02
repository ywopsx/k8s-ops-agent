"""rehearsal 테스트용 가짜 kubectl과 시계. 실제 클러스터에 접속하지 않는다."""
import itertools
import json
import subprocess

PDB_429 = "Error from server (TooManyRequests): Cannot evict pod as it would violate the pod's disruption budget.\n"
PDB_500 = ("Error from server (InternalError): This pod has more than one PodDisruptionBudget, "
           "which the eviction subresource does not support.\n")
FORBIDDEN = 'Error from server (Forbidden): pods "x" is forbidden: User "viewer" cannot create resource "pods/eviction"\n'


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def pod(name, ns="app", node="w1", owner=("ReplicaSet", "web-rs", "uid-web-rs"), ready=True, labels=None,
        annotations=None, phase="Running"):
    md = {"name": name, "namespace": ns, "uid": f"uid-{name}", "labels": labels or {},
          "annotations": annotations or {}}
    if owner:
        kind, oname, ouid = owner
        md["ownerReferences"] = [{"kind": kind, "name": oname, "uid": ouid, "controller": True}]
    return {"metadata": md, "spec": {"nodeName": node},
            "status": {"phase": phase, "conditions": [{"type": "Ready", "status": "True" if ready else "False"}]}}


class FakeCluster:
    """kubectl 명령 일부를 흉내 낸다.

    evict: Pod 이름 -> "pdb" | "pdb-multiple" | "gone" | "error" | "raise" (없으면 성공)
    replace: 컨트롤러 uid -> ("ready", 몇 초 뒤 Ready) | ("pending", 스케줄 실패 메시지). 없으면 대체 Pod 없음
    """

    def __init__(self, pods, clock=None, current="kind-test", nodes=("w1", "w2"), evict=None, replace=None,
                 replicasets=None):
        self.pods = {p["metadata"]["uid"]: p for p in pods}
        self.clock = clock or FakeClock()
        self.current = current
        self.nodes = set(nodes)
        self.evict = evict or {}
        self.replace = replace or {}
        self.replicasets = replicasets or {}
        self.calls = []
        self._seq = itertools.count(1)
        self._ready_at = {}

    # --- 상태 -------------------------------------------------------------
    def _view(self, p):
        uid = p["metadata"]["uid"]
        if uid in self._ready_at:
            ready = self.clock() >= self._ready_at[uid]
            p["status"]["conditions"] = [{"type": "Ready", "status": "True" if ready else "False"}]
        return p

    def _remove_and_replace(self, p):
        del self.pods[p["metadata"]["uid"]]
        owner = p["metadata"].get("ownerReferences", [{}])[0]
        mode = self.replace.get(owner.get("uid"))
        if not mode:
            return
        name = f"{p['metadata']['name']}-new{next(self._seq)}"
        new = pod(name, ns=p["metadata"]["namespace"], node="w2",
                  owner=(owner["kind"], owner["name"], owner["uid"]), ready=False, labels=p["metadata"]["labels"])
        if mode[0] == "ready":
            self._ready_at[new["metadata"]["uid"]] = self.clock() + mode[1]
        else:
            new["spec"]["nodeName"] = ""
            new["status"] = {"phase": "Pending", "conditions": [
                {"type": "PodScheduled", "status": "False", "reason": "Unschedulable", "message": mode[1]}]}
        self.pods[new["metadata"]["uid"]] = new

    # --- kubectl ----------------------------------------------------------
    def __call__(self, args, input=None):
        self.calls.append(list(args))
        a = list(args)
        if "--context" in a:
            i = a.index("--context")
            del a[i:i + 2]
        ok = lambda out="": subprocess.CompletedProcess(args, 0, out, "")
        fail = lambda err: subprocess.CompletedProcess(args, 1, "", err)
        items = lambda ps: ok(json.dumps({"items": [self._view(p) for p in ps]}))

        if a == ["config", "current-context"]:
            return ok(self.current + "\n")
        if a[:2] == ["get", "node"]:
            return ok(f"node/{a[2]}") if a[2] in self.nodes else fail(f'Error from server (NotFound): nodes "{a[2]}" not found')
        if a[:3] == ["get", "pods", "--all-namespaces"]:
            node = a[4].split("=", 1)[1]
            return items([p for p in self.pods.values() if p["spec"]["nodeName"] == node])
        if a[:3] == ["get", "pods", "-n"]:
            return items([p for p in self.pods.values() if p["metadata"]["namespace"] == a[3]])
        if a[:2] == ["get", "replicaset"]:
            rs = self.replicasets.get((a[4], a[2]))
            return ok(json.dumps(rs)) if rs else fail("Error from server (NotFound)")
        if a[0] in ("cordon", "uncordon"):
            return ok()
        if a[:2] == ["create", "--raw"]:
            # /api/v1/namespaces/<ns>/pods/<name>/eviction
            ns, name = a[2].split("/")[4], a[2].split("/")[6]
            target = next((p for p in self.pods.values()
                           if p["metadata"]["namespace"] == ns and p["metadata"]["name"] == name), None)
            behavior = self.evict.get(name)
            if behavior == "raise":
                raise RuntimeError("연결 끊김")
            if behavior == "pdb":
                return fail(PDB_429)
            if behavior == "pdb-multiple":
                return fail(PDB_500)
            if behavior == "error":
                return fail(FORBIDDEN)
            if target is None or behavior == "gone":
                if target is not None:
                    self._remove_and_replace(target)
                return fail(f'Error from server (NotFound): pods "{name}" not found\n')
            self._remove_and_replace(target)
            return ok('{"kind":"Status","status":"Success"}')
        raise AssertionError(f"예상하지 못한 kubectl 호출: {args}")

    def write_calls(self):
        return [c for c in self.calls if c[0] in ("cordon", "uncordon", "create", "delete", "patch", "apply")]

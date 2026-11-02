from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from preflight import collect

from .compare import compare, predict
from .drain import drain_node
from .guard import GuardError, resolve_context
from .kube import Kube, Runner, kubectl_runner
from .report import to_json, to_markdown


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rehearsal",
                                description="kind 클러스터에서 노드를 실제로 바꿔 보는 검증 (kind- 컨텍스트에서만 실행)")
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("drain", help="노드를 cordon·drain하고 Pod별 결과와 걸린 시간을 리포트로 남긴다")
    d.add_argument("--node", required=True, help="drain할 노드 이름")
    d.add_argument("--context", help="kubeconfig 컨텍스트 (kind-로 시작해야 함, 기본: 현재 컨텍스트)")
    d.add_argument("--timeout", type=float, default=120.0, help="eviction과 대체 Pod 대기에 쓰는 전체 시간(초)")
    d.add_argument("--interval", type=float, default=2.0, help="재시도·조회 간격(초)")
    d.add_argument("--keep-cordoned", action="store_true", help="끝난 뒤 uncordon하지 않는다 (조사용)")
    d.add_argument("--include-system", action="store_true", help="예측 비교에 시스템 네임스페이스도 포함")
    d.add_argument("--out", default="out/rehearsal", help="결과를 저장할 디렉터리")
    d.add_argument("--kubectl", default="kubectl", help="kubectl 실행 파일 경로")
    return p


def main(argv: Optional[list[str]] = None, runner: Optional[Runner] = None) -> int:
    args = build_parser().parse_args(argv)
    run = runner or kubectl_runner(args.kubectl)

    # 1. 안전장치: kind- 컨텍스트가 아니면 다른 명령을 하나도 실행하지 않고 멈춘다.
    try:
        context = resolve_context(run, args.context)
    except GuardError as e:
        print(f"[stop] {e}", file=sys.stderr)
        return 2
    kube = Kube(run, context)
    if not kube.node_exists(args.node):
        print(f"[stop] 노드 {args.node}가 {context}에 없습니다.", file=sys.stderr)
        return 2

    # 2. drain 직전 상태를 저장하고 preflight로 예측한다 (읽기 전용).
    started = datetime.now()
    out_dir = Path(args.out) / started.strftime("%Y%m%d-%H%M%S")
    snap = collect.from_cluster(args.kubectl, context)
    collect.save(snap, out_dir / "snapshot")
    findings = predict(snap, args.include_system)

    # 3. drain (끝나면 항상 uncordon, --keep-cordoned 제외)
    result = drain_node(kube, args.node, timeout=args.timeout, interval=args.interval,
                        keep_cordoned=args.keep_cordoned)
    result.started_at = started.isoformat(timespec="seconds")

    # 4. 리포트
    rows = compare(result.pods, findings, snap, args.include_system)
    md = to_markdown(result, rows)
    (out_dir / f"drain-{args.node}.md").write_text(md, encoding="utf-8")
    (out_dir / f"drain-{args.node}.json").write_text(to_json(result, rows), encoding="utf-8")
    print(md)
    print(f"결과: {out_dir}/")
    return 0 if result.ok else 1

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import collect
from .checks import Context, run_all
from .models import Severity
from .report import to_json, to_markdown


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="preflight",
        description="Kubernetes(EKS) 업그레이드 전에 위험 요소를 찾는 읽기 전용 점검 도구",
    )
    p.add_argument("--target-version", required=True, help="올릴 버전 (예: 1.33)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--context", help="kubeconfig context (기본: 현재 context)")
    src.add_argument("--from-dir", help="저장해 둔 스냅샷 디렉터리에서 읽기 (클러스터 접속 없음)")
    p.add_argument("--save-snapshot", help="조회한 리소스를 이 디렉터리에 저장")
    p.add_argument("--cni-baseline", help="aws-node 환경변수 기준값 JSON 파일 (예: {\"ENABLE_PREFIX_DELEGATION\": \"true\"})")
    p.add_argument("--include-system", action="store_true", help="kube-system 등 시스템 네임스페이스도 점검")
    p.add_argument("--format", choices=["md", "json"], default="md")
    p.add_argument("--fail-on", choices=["high", "medium", "never"], default="high",
                   help="이 심각도 이상이 있으면 종료 코드 1 (CI에서 사용)")
    p.add_argument("--kubectl", default="kubectl", help="kubectl 실행 파일 경로")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    snap = collect.from_dir(args.from_dir) if args.from_dir else collect.from_cluster(args.kubectl, args.context)
    if args.save_snapshot:
        collect.save(snap, args.save_snapshot)

    baseline = json.loads(Path(args.cni_baseline).read_text(encoding="utf-8")) if args.cni_baseline else {}
    ctx = Context(target_version=args.target_version, cni_expected_env=baseline, include_system=args.include_system)
    findings = run_all(snap, ctx)

    print(to_json(findings) if args.format == "json" else to_markdown(findings, args.target_version))

    if args.fail_on == "never":
        return 0
    threshold = Severity.parse(args.fail_on)
    return 1 if any(f.severity >= threshold for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())

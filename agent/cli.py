"""python -m agent analyze | eval"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from rehearsal.guard import GuardError

from .alert import load_alert
from .eval import load_scenarios, score, summary_markdown
from .llm import ClaudeCLIBackend
from .loop import MODE_AGENT, MODE_FIXED, analyze, load_runbooks
from .report import to_json, to_markdown
from .runtime import DEFAULT_KUBECONFIG, RUNBOOKS_DIR, check_context, server_specs
from .tools import MCPToolBox


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--kubeconfig", type=Path, default=DEFAULT_KUBECONFIG,
                   help="읽기 전용(view) kubeconfig. 현재 컨텍스트가 kind-로 시작해야 한다")
    p.add_argument("--model", help="claude -p에 넘길 모델 (없으면 기본 모델)")
    p.add_argument("--max-tool-calls", type=int, default=5, help="모드 C에서 LLM이 고를 수 있는 도구 호출 수")
    p.add_argument("--log-lines", type=int, default=50, help="LLM에 보내는 로그 최근 줄 수")
    p.add_argument("--runbooks", type=Path, default=RUNBOOKS_DIR)
    p.add_argument("--no-preflight", action="store_true", help="preflight MCP 서버를 붙이지 않는다")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m agent", description="알림 1차 분석 에이전트 (읽기 전용)")
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyze", help="알림 파일 하나를 분석한다")
    a.add_argument("--alert", type=Path, required=True, help="Alertmanager webhook 형식 JSON")
    a.add_argument("--mode", choices=[MODE_AGENT, MODE_FIXED], default=MODE_AGENT)
    a.add_argument("--out", type=Path, default=Path("out/agent/reports"))
    _common(a)
    e = sub.add_parser("eval", help="시나리오 × 반복 × 모드로 평가한다")
    e.add_argument("--scenarios", type=Path, default=Path("demo/agent/scenarios.json"))
    e.add_argument("--alerts-dir", type=Path, default=Path("out/agent/alerts"))
    e.add_argument("--repeats", type=int, default=3)
    e.add_argument("--modes", default="c,a")
    e.add_argument("--out", type=Path, default=Path("out/agent/eval"))
    _common(e)
    return parser


def _write(out_dir: Path, stem: str, analysis, runbooks_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    runbook = analysis.runbook(runbooks_dir)
    (out_dir / f"{stem}.md").write_text(to_markdown(analysis, runbook), encoding="utf-8")
    (out_dir / f"{stem}.json").write_text(to_json(analysis, runbook), encoding="utf-8")
    return out_dir / f"{stem}.md"


async def _with_toolbox(args, body):
    servers, cfg = server_specs(args.kubeconfig, with_preflight=not args.no_preflight)
    try:
        async with MCPToolBox(servers) as box:
            return await body(box)
    finally:
        cfg.unlink(missing_ok=True)


def cmd_analyze(args) -> int:
    alert = load_alert(args.alert)
    backend = ClaudeCLIBackend(model=args.model)
    runbooks = load_runbooks(args.runbooks)

    async def body(box):
        return await analyze(alert, box, backend, args.mode, runbooks, args.max_tool_calls, args.log_lines)

    analysis = asyncio.run(_with_toolbox(args, body))
    stem = f"{datetime.now():%Y%m%d-%H%M%S}-{args.alert.stem}-{args.mode}"
    path = _write(args.out, stem, analysis, args.runbooks)
    print(f"1순위 원인: {analysis.top_cause or '-'}  ({analysis.duration_s}초, LLM 선택 도구 호출 {analysis.agent_tool_calls}회)")
    print(f"리포트: {path}")
    if analysis.error:
        print(f"[오류] {analysis.error}", file=sys.stderr)
        return 1
    return 0


def cmd_eval(args) -> int:
    scenarios = load_scenarios(args.scenarios)
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    backend = ClaudeCLIBackend(model=args.model)
    runbooks = load_runbooks(args.runbooks)
    out_dir = args.out / f"{datetime.now():%Y%m%d-%H%M%S}-{args.model or 'default'}"
    runs = []

    async def body(box):
        for s in scenarios:
            alert = load_alert(args.alerts_dir / s.alert)
            for mode in modes:
                for i in range(1, args.repeats + 1):
                    a = await analyze(alert, box, backend, mode, runbooks, args.max_tool_calls, args.log_lines)
                    _write(out_dir / "runs", f"{s.id}-{mode}-{i}", a, args.runbooks)
                    model = ",".join(a.totals()["models"]) or (args.model or "default")
                    run = score(s, mode, i, model, a)
                    runs.append(run)
                    print(f"[{s.id} {mode.upper()} #{i}] 1순위 {run.top_cause} (정답 {s.expected}) "
                          f"{'맞음' if run.correct else '틀림'} · {run.duration_s}초 · LLM 선택 도구 {run.agent_tool_calls}회"
                          + (f" · 오류: {run.error}" if run.error else ""), flush=True)

    asyncio.run(_with_toolbox(args, body))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "runs.json").write_text(json.dumps([asdict(r) for r in runs], ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    (out_dir / "summary.md").write_text(summary_markdown(runs, scenarios), encoding="utf-8")
    print(f"평가 결과: {out_dir / 'summary.md'}")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        context = check_context(args.kubeconfig)
    except GuardError as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 2
    print(f"컨텍스트: {context} (kubeconfig {args.kubeconfig})", file=sys.stderr)
    return cmd_analyze(args) if args.command == "analyze" else cmd_eval(args)

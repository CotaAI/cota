"""Offline evaluation commands; independent of Channels and service startup."""
import asyncio
from pathlib import Path
import sys

from .artifacts import compare_runs, exit_code, write_comparison
from .runner import evaluate, rejudge


def console_progress(event):
    kind = event['event']
    message = None
    if kind == 'run_started':
        message = (f"开始评测：{event['case_runs']} 个案例运行，{event['turns']} 轮；评委：{event['judge']}\n"
                   f"结果目录：{event['output']}")
    elif kind == 'case_started':
        message = f"[{event['index']}/{event['total']}] {event['case_id']}（第 {event['repetition']} 次）"
    elif kind in ('stage_started', 'heartbeat'):
        phase = {'bot': 'Bot 执行', 'judge': 'LLM 评判'}[event['phase']]
        message = f"  第 {event['turn']}/{event['turns']} 轮 · {phase}"
        if kind == 'heartbeat':
            message += f"，仍在等待，已用 {event['elapsed_seconds']:.0f}s（本阶段超时 {event['timeout_seconds']:g}s）"
    elif kind == 'turn_finished':
        if event['execution']['status'] == 'error':
            message = f"  Bot 执行失败：{event['execution']['error_type']}；跳过该案例剩余轮次"
        elif event['judge'] == 'error':
            message = '  评判失败，已保存诊断记录，继续后续轮次'
    elif kind == 'case_finished':
        s = event['summary']
        message = (f"  {s['verdict']} · 符合 {s['pass']}/{s['total']}，不符合 {s['fail']}，"
                   f"无法判断 {s['inconclusive']}，未评判 {s['total'] - s['pass'] - s['fail'] - s['inconclusive']}")
    elif kind == 'run_finished':
        s = event['summary']
        label = '评测完成' if event['status'] == 'completed' else '评测中断'
        message = (f"{label}（{event['elapsed_seconds']:.1f}s）：符合 {s['criteria_passed']}/{s['criteria_total']}，"
                   f"不符合 {s['criteria_failed']}，无法判断 {s['criteria_inconclusive']}，"
                   f"未评判 {s['criteria_unjudged']}；执行错误 {s['turns_errored']}，评判错误 {s['judge_errors']}")
    if message:
        print(message, file=sys.stderr, flush=True)


def run_eval(args):
    try:
        if args.eval_action == 'compare':
            write_comparison(args.output, compare_runs(args.runs))
            print(f'评测对比：{Path(args.output).resolve() / "report.md"}')
            return
        print('准备评测：读取案例与配置…', file=sys.stderr, flush=True)
        if args.eval_action == 'judge':
            result = asyncio.run(rejudge(args.run, args.config, output=args.output,
                                         judge_timeout=args.judge_timeout, progress=console_progress))
        else:
            result = asyncio.run(evaluate(args.config, output=args.output, cases=args.cases,
                                         repeat=args.repeat, case_ids=args.case,
                                         timeout=args.timeout, judge_timeout=args.judge_timeout, debug=args.debug,
                                         progress=console_progress))
        output = Path(args.output).resolve() if args.output else Path(args.config).resolve() / 'workspace/evaluations' / result['run_id']
        print(f'评测报告：{output / "report.md"}\n标准数据：{output / "results.json"}')
        raise SystemExit(exit_code(result))
    except (ValueError, OSError) as error:
        # Config/schema errors are actionable. Provider errors are captured per turn by the runner.
        print(f'评测无法完成：{error}', file=sys.stderr)
        raise SystemExit(2) from error


def add_eval_parser(subparsers):
    parser = subparsers.add_parser('eval', allow_abbrev=False, help='运行 Bot 对话验证，用 LLM 逐项评判 reply-review')
    parser.set_defaults(func=run_eval, eval_action='run')
    parser.add_argument('--config', default='./', help='被测 Bot 目录；使用其实际定义及模型配置')
    parser.add_argument('--cases', help='验证文件或目录，默认 Bot 的 policy/eval/')
    parser.add_argument('--case', action='append', help='选择 文件相对路径::案例name，可重复')
    parser.add_argument('--repeat', type=int, default=1, help='每个案例独立重复次数')
    parser.add_argument('--output', help='新的结果目录，默认 workspace/evaluations/<run_id>')
    parser.add_argument('--timeout', type=float, default=300, help='每轮 Bot 执行超时秒数')
    parser.add_argument('--judge-timeout', type=float, default=120, help='每轮评判超时秒数')
    parser.add_argument('--debug', action='store_true', help='额外保存 Bot 的模型请求诊断')
    parser.add_argument('--log', default='WARNING')
    commands = parser.add_subparsers(dest='eval_action')
    judge = commands.add_parser('judge', allow_abbrev=False, help='仅重新评判已有 Trace，不执行 Bot 或工具')
    judge.set_defaults(func=run_eval)
    judge.add_argument('--run', required=True, help='已有评测目录')
    judge.add_argument('--config', default='./', help='提供评委 endpoints.yml 的目录')
    judge.add_argument('--judge-timeout', type=float, default=120)
    judge.add_argument('--output', required=True, help='新的结果目录')
    judge.add_argument('--log', default='WARNING')
    compare = commands.add_parser('compare', help='按案例和评测项对比多个结果')
    compare.set_defaults(func=run_eval)
    compare.add_argument('runs', nargs='+')
    compare.add_argument('--output', required=True, help='新的对比结果目录')
    compare.add_argument('--log', default='WARNING')

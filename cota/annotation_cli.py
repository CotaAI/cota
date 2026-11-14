"""Policy files: read conversations on export; import only validates and writes YAML."""
import asyncio
from pathlib import Path
import sys

from cota.annotation_files import export_worksheet, read_worksheet, write_worksheet
from cota.store import Store
from cota.utils.io import read_yaml_from_path


def _budgets(config):
    config_data = read_yaml_from_path(str(Path(config) / "agent.yml")) or {}
    policy = config_data.get("policy", {})
    return {key: policy[key] for key in ('max_policies', 'max_chars') if key in policy}


def _store(config):
    path = Path(config).resolve()
    endpoints = read_yaml_from_path(str(path / 'endpoints.yml')) or {}
    settings = dict(endpoints.get('base_store', {}))
    if settings.get('type', 'memory').lower() != 'sql':
        raise ValueError('独立导出命令需要 SQL Store。内存会话请在 Bot 进程内使用 export_worksheet。')
    if settings.get('dialect', 'mysql+pymysql').startswith('sqlite'):
        database = settings.get('db', 'cota.db')
        if database == ':memory:':
            raise ValueError('SQLite 内存库不能由独立标注命令读取，请使用持久数据库。')
        settings['db'] = str((path / database).resolve())
        if not Path(settings['db']).is_file():
            raise ValueError(f'会话数据库不存在：{settings["db"]}')
    return Store.create(settings)


async def _run(args):
    store = None
    try:
        if args.operation == 'export':
            store = _store(args.config)
            dst = await store.load(args.session)
            if dst is None:
                raise ValueError('会话不存在')
            if not dst.events:
                raise ValueError('会话没有可标注的对话')
            write_worksheet(args.output, export_worksheet(dst))
            print(f'已导出：{args.output}\n编辑 policies 中的 name / steps；Bot 内按顺序填写 thought、skills、result、reply。\n'
                  'result 可选，用自然语言写案例假设的结果条件，不代表真实执行结果。')
        else:
            document = read_worksheet(args.input, **_budgets(args.config))
            write_worksheet(args.output, document)
            print(f'已生成 Policy 文件：{args.output}\n'
                  '将文件放入 Bot 的 policy/ 目录，重新加载 Agent 即可生效。')
    finally:
        engine = getattr(store, 'engine', None)
        if engine is not None:
            engine.dispose()


def run_annotation(args):
    try:
        asyncio.run(_run(args))
    except Exception as exc:
        print(f'标注操作失败：{exc}', file=sys.stderr)
        raise SystemExit(1) from exc


def add_annotation_parser(subparsers):
    parser = subparsers.add_parser('annotate', help='导出对话标注文件、导入业务流程并生成 Policy')
    operations = parser.add_subparsers(dest='operation', required=True)
    for name, help_text in [('export', '导出可填写的对话标注文件'), ('import', '校验并写入 Policy 文件')]:
        command = operations.add_parser(name, help=help_text)
        command.add_argument('--config', default='./', help='Bot 配置目录')
        command.add_argument('--output', required=True, help='新文件路径（不会覆盖已有文件）')
        command.add_argument('--log', default='INFO')
        if name == 'export':
            command.add_argument('--session', required=True, help='需要标注的会话')
        else:
            command.add_argument('--input', required=True, help='填写后的对话标注文件')
        command.set_defaults(func=run_annotation)

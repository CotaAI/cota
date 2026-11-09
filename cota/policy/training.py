"""cota train: compile Policy data without starting a Bot, Store or Pi worker."""
import asyncio
from pathlib import Path
import sys

from cota.utils.io import read_yaml_from_path
from .factory import load_policy, train_policy
from .resources import PolicyResources


async def train_bot(path, *, check=False):
    root = Path(path)
    config_path = root / 'agent.yml'
    if not config_path.is_file():
        raise ValueError(f'Bot configuration missing: {config_path}')
    config = read_yaml_from_path(str(config_path)) or {}
    settings = config.get('policy', {})
    if check:
        policy = load_policy(root, settings)
        return {'checked': True, 'type': type(policy).__name__, 'policies': len(policy.policies)}
    resources = PolicyResources(read_yaml_from_path(str(root / 'endpoints.yml')) or {})
    try:
        return await train_policy(root, settings, resources.services())
    finally:
        await resources.close()


def run_train(args):
    try:
        result = asyncio.run(train_bot(args.config, check=args.check))
    except Exception as error:
        print(f'Policy 训练/校验失败：{error}', file=sys.stderr)
        raise SystemExit(1) from error
    if args.check:
        print(f'Policy 产物校验通过：{result["type"]}，{result["policies"]} 个案例')
    else:
        print(f'Policy 训练完成：{result["type"]}，{result["policies"]} 个案例\n'
              f'产物：{result["artifact"]}\n重新加载 Bot 后生效。train 构建策略产物，不一定更新模型权重。')


def add_train_parser(subparsers):
    parser = subparsers.add_parser('train', help='训练 Policy：构建索引、embedding、规则或模型检索语料')
    parser.add_argument('--config', default='./', help='Bot 配置目录')
    parser.add_argument('--log', default='INFO', help='日志级别')
    parser.add_argument('--check', action='store_true', help='只检查当前配置和训练产物是否匹配')
    parser.set_defaults(func=run_train)

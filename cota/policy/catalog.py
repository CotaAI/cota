"""Ordered business examples, shared by authoring, annotation and Pi guidance.

The only public document is ``policies: [{name, steps}]``. Bot steps contain
ordered singleton thought/skills/result/reply items. Results are hypothetical
observations, never actual tool evidence. No generated phase schema or
synthetic assistant reasoning is introduced. Entire examples are budgeted and
presented as examples; the model judges relevance against the real conversation.
"""
import re
from copy import deepcopy
from pathlib import Path

import yaml

from cota.retrieval.chunker import parse_frontmatter


class _StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError('YAML object keys must be strings')
            if key in seen:
                raise ValueError(f'Duplicate YAML key: {key}; use separate ordered list items')
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


_H2 = re.compile(r'^##\s+(.+)$', re.MULTILINE)
_TOP_ITEM = re.compile(r'^- (User|Bot):\s*(.*)', re.IGNORECASE)
_BOT_ITEM = re.compile(r'^\s{2,}- (Thought|Skills|Result|Reply):\s*(.*)', re.IGNORECASE)


def _parse_policies_from_markdown(body):
    sections = []
    current = None
    for line in body.split('\n'):
        m = _H2.match(line)
        if m:
            current = {'name': m.group(1).strip(), 'lines': []}
            sections.append(current)
        elif current is not None:
            current['lines'].append(line)

    policies = []
    for section in sections:
        steps = _parse_steps(section['lines'])
        if steps:
            policies.append({'name': section['name'], 'steps': steps})
    return policies


def _flush_item(kind, parts, items):
    if kind is None:
        return
    text = ' '.join(parts).strip()
    if kind == 'skills':
        items.append({'skills': [s.strip() for s in text.split(',') if s.strip()]})
    else:
        items.append({kind: text})


def _flush_bot(bot_items, steps):
    if bot_items:
        steps.append({'bot': list(bot_items)})
        bot_items.clear()


def _parse_steps(lines):
    steps = []
    bot_items = []
    cur_kind = None
    cur_parts = []
    in_bot = False
    user_parts = []
    in_user = False

    for line in lines:
        top = _TOP_ITEM.match(line)
        if top:
            if in_user and user_parts:
                steps.append({'user': ' '.join(user_parts).strip()})
                user_parts.clear()
            if in_bot:
                _flush_item(cur_kind, cur_parts, bot_items)
                cur_kind, cur_parts = None, []
                _flush_bot(bot_items, steps)
            tag = top.group(1).lower()
            rest = top.group(2).strip()
            if tag == 'user':
                in_user, in_bot = True, False
                user_parts = [rest] if rest else []
            else:
                in_user, in_bot = False, True
            continue

        if in_bot:
            sub = _BOT_ITEM.match(line)
            if sub:
                _flush_item(cur_kind, cur_parts, bot_items)
                cur_kind = sub.group(1).lower()
                cur_parts = [sub.group(2).strip()] if sub.group(2).strip() else []
            elif cur_kind is not None and line.strip():
                cur_parts.append(line.strip())
            continue

        if in_user and line.strip():
            user_parts.append(line.strip())

    if in_user and user_parts:
        steps.append({'user': ' '.join(user_parts).strip()})
    if in_bot:
        _flush_item(cur_kind, cur_parts, bot_items)
        _flush_bot(bot_items, steps)
    return steps


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def validate_policy(value):
    if not isinstance(value, dict) or set(value) != {'name', 'steps'} or not _text(value['name']):
        raise ValueError('Policy requires exactly a nonempty name and steps')
    steps = value['steps']
    if not isinstance(steps, list) or not steps:
        raise ValueError('Policy steps must be a nonempty ordered list')
    has_bot = False
    for step in steps:
        if not isinstance(step, dict) or len(step) != 1:
            raise ValueError('Each step must contain only user or bot')
        if 'user' in step:
            if not _text(step['user']):
                raise ValueError('user must be nonempty text')
        elif 'bot' in step:
            has_bot = True
            items = step['bot']
            if not isinstance(items, list) or not items:
                raise ValueError('bot must be a nonempty ordered list of thought, skills, result or reply items')
            for item in items:
                if not isinstance(item, dict) or len(item) != 1:
                    raise ValueError('Each bot item must contain exactly one of thought, skills, result or reply')
                kind, content = next(iter(item.items()))
                if kind == 'skills':
                    if (not isinstance(content, list) or not content or any(not _text(s) for s in content)
                            or len(set(content)) != len(content)):
                        raise ValueError('skills must be a nonempty list of unique Skill names')
                elif kind not in ('thought', 'result', 'reply') or not _text(content):
                    raise ValueError('Bot items require skills, or nonempty thought/result/reply text')
        else:
            raise ValueError('Each step must contain only user or bot')
    if not has_bot:
        raise ValueError('Policy needs at least one bot step')
    return deepcopy(value)


def policy_skills(policy):
    return list(dict.fromkeys(name for step in policy['steps'] for item in step.get('bot', [])
                              for name in item.get('skills', [])))


def policy_thoughts(policy):
    """Attribute thoughts to behaviors, skipping observations; indices are zero-based."""
    thoughts = []
    for step_index, step in enumerate(policy['steps']):
        items = step.get('bot', [])
        for index, item in enumerate(items):
            if 'thought' not in item:
                continue
            target_index = next((i for i in range(index + 1, len(items))
                                 if 'skills' in items[i] or 'reply' in items[i]), None)
            target = next(iter(items[target_index])) if target_index is not None else 'continuation'
            thoughts.append({'policy': policy['name'], 'step': step_index, 'item': index,
                             'target': target, 'target_item': target_index, 'text': item['thought']})
    return thoughts


_GUIDANCE = (
    '以下是运营提供的业务 Policy 示例，不是系统自动执行脚本。示例不是当前对话。\n'
    '请结合真实对话、当前用户需求及实际工具结果判断是否适用、当前走到哪一步；不要逐字匹配用户表达。\n'
    '尚未发生的示例用户消息不能视为已收到，示例回复不能作为事实或查询结果。\n'
    'thought 是人工业务指导，不是模型已经产生的思考，也无需向用户复述。'
    '其位置侧重指导后续 skills 或 reply；条件仍以真实执行证据为准。\n'
    'skills 表示期望的业务能力及顺序；阅读 Skill 不代表业务已执行或完成。'
    'reply 是话术示例，回复内容必须根据当前事实调整。\n'
    'result 描述案例假设观察到的结果，是分支适用条件；示例 result 不是实际工具结果，也不证明 Skill 已执行。'
    '只有真实执行证据支持时才参考对应分支；结果缺失、失败或无法确认时，不得用示例结果补齐事实，'
    '应按实际情况补充查询、澄清或说明无法确认。不同案例的结果不能拼成一次真实执行。\n'
)


def _render(policy, focus=None):
    lines = [f"Policy: {policy['name']}"]
    thoughts = {(t['step'], t['item']): t for t in policy_thoughts(policy)}
    for step_index, step in enumerate(policy['steps']):
        if focus is not None and step_index > focus:
            break
        if 'user' in step:
            lines.append(f"  示例 User: {step['user']}")
            continue
        lines.append('  示例 Bot:')
        for index, item in enumerate(step['bot']):
            # Prior replies may contain the question/condition answered by a
            # later "yes". Keep them, but guide only the selected business step.
            if focus is not None and step_index < focus and 'thought' in item:
                continue
            if 'thought' in item:
                target = thoughts[step_index, index]['target']
                label = {'skills': '能力选择与使用', 'reply': '结果处理与回复', 'continuation': '后续处理'}[target]
                lines.append(f"    Thought（{label}）: {item['thought']}")
            elif 'skills' in item:
                lines.append('    Skills: ' + ' → '.join(item['skills']))
            elif 'result' in item:
                lines.append('    Result（示例结果条件）: ' + item['result'])
            else:
                lines.append('    Reply 示例: ' + item['reply'])
    return '\n'.join(lines)


class PolicyCatalog:
    def __init__(self, policies=(), *, max_policies=8, max_chars=12000):
        if any(type(n) is not int or n < 1 for n in (max_policies, max_chars)):
            raise ValueError('Policy budgets must be positive integers')
        if isinstance(policies, (str, bytes, dict)):
            raise ValueError('policies must be a collection')
        try:
            self._policies = [validate_policy(p) for p in policies]
        except TypeError as exc:
            raise ValueError('policies must be a collection') from exc
        names = [p['name'] for p in self._policies]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate policy name')
        for policy in self._policies:
            if len(_GUIDANCE + '\n' + _render(policy)) > max_chars:
                raise ValueError(f"Policy {policy['name']} exceeds max_chars={max_chars}")
        self.max_policies, self.max_chars = max_policies, max_chars

    @property
    def policies(self):
        return deepcopy(self._policies)

    @classmethod
    def from_document(cls, document, **budgets):
        if not isinstance(document, dict) or set(document) != {'policies'} or not isinstance(document['policies'], list):
            raise ValueError('Expected policies: [{name, steps}]')
        return cls(document['policies'], **budgets)

    @classmethod
    def load(cls, path, **budgets):
        if path is None or not Path(path).exists():
            return cls(**budgets)
        path = Path(path)
        if path.is_dir():
            files = sorted((p for p in path.iterdir()
                            if p.is_file() and p.suffix.lower() in ('.md', '.yaml', '.yml')
                            and p.name.lower() != 'readme.md'),
                           key=lambda p: p.name)
        else:
            files = [path]
        policies = []
        for source in files:
            text = source.read_text(encoding='utf-8')
            if source.suffix.lower() == '.md':
                _, body = parse_frontmatter(text)
                parsed = _parse_policies_from_markdown(body)
                if parsed:
                    policies.extend(cls.from_document({'policies': parsed}, **budgets).policies)
            else:
                try:
                    doc = yaml.load(text, Loader=_StrictLoader)
                except yaml.YAMLError as exc:
                    raise ValueError(f'Invalid Policy YAML: {source}') from exc
                policies.extend(cls.from_document(doc, **budgets).policies)
        return cls(policies, **budgets)

    def validate_skills(self, names):
        available = set(names)
        unknown = sorted({s for p in self._policies for s in policy_skills(p)} - available)
        if unknown:
            raise ValueError(f'Unknown policy Skill names: {", ".join(unknown)}')

    def guidance(self, available_skills, read_skills, *, matches=None):
        available, read = set(available_skills), set(read_skills)
        chosen, blocks, omitted, selected_thoughts = [], [], [], []
        # Read evidence affects priority only. It must not be mistaken for a
        # completed business step or hide guidance needed before the first read.
        ordered = sorted(self._policies, key=lambda p: not bool(set(policy_skills(p)) & read))
        assessments = {}
        if matches is not None:
            by_name = {p['name']: p for p in self._policies}
            assessments = {m['name']: m for m in matches}
            ordered = [by_name[m['name']] for m in matches if m['status'] != 'not_applicable']
        for policy in ordered:
            if not set(policy_skills(policy)) <= available:
                continue
            assessment = assessments.get(policy['name'])
            focus = assessment.get('step') if assessment else None
            block = _render(policy, focus)
            if assessment:
                label = {'candidate': '相关候选，适用性仍需判断', 'conditional': '条件待确认',
                         'applicable': '模型判定当前适用，仍需核对实际事实'}[assessment['status']]
                focus = assessment.get('step')
                annotated = f'参考状态：{label}；关注步骤：{focus if focus is not None else "完整案例"}\n' + block
                # Optional selection labels must not make a validated whole
                # example unusable at its exact catalog budget.
                if len(_GUIDANCE + '\n' + '\n\n'.join([*blocks, annotated])) <= self.max_chars:
                    block = annotated
            reason = ('max_policies' if len(chosen) >= self.max_policies else 'max_chars'
                      if len(_GUIDANCE + '\n' + '\n\n'.join([*blocks, block])) > self.max_chars else None)
            if reason:
                omitted.append({'name': policy['name'], 'reason': reason})
                continue
            chosen.append(policy)
            blocks.append(block)
            selected_thoughts.extend(t for t in policy_thoughts(policy) if focus is None or t['step'] == focus)
        # Ranking chooses the cases within the budget, not their display order.
        # The same selected cases must render identically after rank-only changes.
        stable_blocks = [block for _, block in sorted(zip(chosen, blocks), key=lambda item: item[0]['name'])]
        return {'text': _GUIDANCE + '\n' + '\n\n'.join(stable_blocks) if blocks else '',
                'policies': deepcopy(chosen), 'thoughts': selected_thoughts,
                'omitted_policies': omitted}


__all__ = ['PolicyCatalog', 'validate_policy', 'policy_skills', 'policy_thoughts']

"""One editable Policy format for authored examples and transcript-derived edits."""
from pathlib import Path

import yaml

from cota.policy import PolicyCatalog, _StrictLoader


class _WorksheetDumper(yaml.SafeDumper):
    pass


def _string(dumper, value):
    return dumper.represent_scalar('tag:yaml.org,2002:str', value, style='|' if '\n' in value else None)


_WorksheetDumper.add_representer(str, _string)


def export_worksheet(dst):
    steps = []
    for event in dst.events:
        text = event.text
        if event.payload.get('attachments'):
            text = (text + '\n' if text else '') + '[附件：' + '、'.join(a['name'] for a in event.payload['attachments']) + ']'
        if event.type == 'user_utter' and text.strip():
            steps.append({'user': text})
        elif event.type == 'bot_utter' and text.strip():
            if steps and 'bot' in steps[-1]:
                steps[-1]['bot'].append({'reply': text})
            else:
                steps.append({'bot': [{'reply': text}]})
    # Observed reads are not prescribed business behavior, and model reasoning
    # is never exported as an operator-authored thought. Tool outputs are not
    # automatically attributed to a Skill or summarized as an authored result.
    # Incomplete transcripts
    # are editable drafts; a completed bot example is required on import/load.
    return {'policies': [{'name': f'对话案例-{dst.session_id}', 'steps': steps}]}


def worksheet_text(document):
    return ("# 按对话顺序填写 steps；每项是 user 或 bot。\n"
            "# bot 是有序列表：可多次填写 thought、skills、result、reply，每项只写一个字段。\n"
            "# thought 写业务判断；skills: [能力名称]；reply 写话术示例。\n"
            "# result 写示例结果条件（可选），不是实际工具结果；不同结果可分别写成命名案例。\n"
            "# 可以改写用户表达、增加/删除步骤、组合多个能力，也可从零编写 policies。\n"
            "# 来自真实对话的回复只是待审核草稿；读取记录不会自动变成正确的业务步骤。\n"
            "# 保存和编辑本文件不会修改真实执行记录。\n\n"
            + yaml.dump(document, Dumper=_WorksheetDumper, allow_unicode=True, sort_keys=False, width=100))


def read_worksheet(path, **budgets):
    try:
        document = yaml.load(Path(path).read_text(encoding='utf-8'), Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f'Policy YAML 格式错误：{exc}') from exc
    policies = PolicyCatalog.from_document(document, **budgets).policies
    if not policies:
        raise ValueError('请填写至少一条 Policy')
    return {'policies': policies}


def write_worksheet(path, document):
    """Write a new editable file; never write back to conversation history."""
    text = worksheet_text(document)
    path = Path(path)
    with path.open('x', encoding='utf-8') as output:
        try:
            output.write(text)
            output.flush()
        except Exception:
            path.unlink(missing_ok=True)
            raise

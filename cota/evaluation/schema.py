"""A small dialogue authoring contract; only user text enters Bot execution."""
import hashlib
import json
from pathlib import Path

import yaml

from cota.policy.catalog import _StrictLoader

SCHEMA_VERSION = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def read_yaml(path):
    try:
        return yaml.load(Path(path).read_text(encoding='utf-8'), Loader=_StrictLoader)
    except yaml.YAMLError as error:
        raise ValueError(f'Invalid YAML: {path}') from error


def text(value):
    return isinstance(value, str) and bool(value.strip())


def load_cases(path):
    path = Path(path).resolve()
    root = path if path.is_dir() else path.parent
    # Selecting a nested file must keep the same identity as evaluating the whole Bot.
    root = next((p for p in (root, *root.parents) if p.name == 'eval' and p.parent.name == 'policy'), root)
    files = sorted(p for p in path.rglob('*') if p.suffix.lower() in ('.yml', '.yaml')) if path.is_dir() else [path]
    cases = []
    for file in files:
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            raise ValueError('Evaluation files must be regular files inside the evaluation directory')
        document = read_yaml(file)
        if not isinstance(document, dict) or set(document) != {'policies'} or not isinstance(document['policies'], list):
            raise ValueError(f'{file}: expected policies: [{{name, steps}}]')
        names = set()
        for item in document['policies']:
            if not isinstance(item, dict) or set(item) != {'name', 'steps'} or not text(item['name']):
                raise ValueError(f'{file}: each case requires name and steps')
            if item['name'] in names:
                raise ValueError(f'{file}: duplicate case name {item["name"]}')
            names.add(item['name'])
            steps = item['steps']
            if not isinstance(steps, list) or not steps or len(steps) % 2:
                raise ValueError(f'{file}: alternate user and bot steps; each user needs reply-review')
            turns = []
            for index in range(0, len(steps), 2):
                user, bot = steps[index:index + 2]
                if not isinstance(user, dict) or set(user) != {'user'} or not text(user['user']):
                    raise ValueError(f'{file}: expected user text')
                if (not isinstance(bot, dict) or set(bot) != {'bot'} or not isinstance(bot['bot'], dict)
                        or set(bot['bot']) != {'reply-review'}):
                    raise ValueError(f'{file}: bot accepts only reply-review')
                reviews = bot['bot']['reply-review']
                if not isinstance(reviews, list) or not reviews or any(not text(r) for r in reviews):
                    raise ValueError(f'{file}: reply-review must contain nonempty text entries')
                if len(set(reviews)) != len(reviews):
                    raise ValueError(f'{file}: duplicate review entry')
                turns.append({'user': user['user'], 'reply-review': reviews})
            source = file.relative_to(root).as_posix()
            cases.append({'id': source + '::' + item['name'], 'name': item['name'], 'source': source,
                          'hash': digest(item), 'turns': turns})
    if not cases:
        raise ValueError(f'No evaluation cases found: {path}')
    return cases


def suite_identity(cases):
    """Hash the selected authored cases, independent of order and repetition count."""
    return {'hash': digest(sorted((c['id'], c['hash']) for c in cases)), 'cases': len(cases),
            'turns': sum(len(c['turns']) for c in cases),
            'criteria': sum(len(t['reply-review']) for c in cases for t in c['turns'])}


def validate_result(value):
    """Reject damaged input with a stable error instead of crashing a comparison script."""
    try:
        if (not isinstance(value, dict) or type(value.get('schema_version')) is not int
                or value['schema_version'] != SCHEMA_VERSION):
            raise ValueError('Unsupported evaluation schema_version')
        if not text(value['run_id']) or not text(value['created_at']) or value['status'] not in ('running', 'completed', 'interrupted'):
            raise ValueError('Invalid evaluation run metadata')
        if not text(value['bot']['hash']) or not text(value['judge']['hash']):
            raise ValueError('Missing Bot or judge identity')
        if not isinstance(value['cases'], list) or not value['cases']:
            raise ValueError('Evaluation results must contain cases')
        identities = set()
        for case in value['cases']:
            if any(not text(case[k]) for k in ('id', 'name', 'hash')) or type(case['repetition']) is not int or case['repetition'] < 1:
                raise ValueError('Invalid evaluation case identity')
            key = case['id'], case['repetition']
            if key in identities:
                raise ValueError('Duplicate evaluation case repetition')
            identities.add(key)
            if not isinstance(case['turns'], list) or not case['turns']:
                raise ValueError('Evaluation case must contain turns')
            for turn in case['turns']:
                if not text(turn['user']) or not isinstance(turn['replies'], list) or any(not isinstance(r, str) for r in turn['replies']):
                    raise ValueError('Invalid evaluation dialogue')
                if turn['execution']['status'] not in ('completed', 'error', 'skipped') or turn['judge']['status'] not in ('completed', 'error', 'skipped'):
                    raise ValueError('Invalid evaluation execution status')
                reviews = turn['judge']['reviews']
                if not isinstance(reviews, list):
                    raise ValueError('Invalid evaluation reviews')
                criteria = turn.get('reply-review', [r['criterion'] for r in reviews])
                if not isinstance(criteria, list) or not criteria or any(not text(c) for c in criteria):
                    raise ValueError('Missing evaluation criteria')
                if turn['judge']['status'] != 'completed' and reviews:
                    raise ValueError('Unfinished judgement cannot contain scored reviews')
                if turn['judge']['status'] == 'completed' and len(reviews) != len(criteria):
                    raise ValueError('Completed judgement must cover all criteria')
                seen = set()
                for review in reviews:
                    index = review['index']
                    if type(index) is not int or not 1 <= index <= len(criteria) or index in seen:
                        raise ValueError('Invalid evaluation review index')
                    seen.add(index)
                    if review['status'] not in ('pass', 'fail', 'inconclusive') or not text(review['reason']):
                        raise ValueError('Invalid evaluation review verdict')
                    if review['criterion'] != criteria[index - 1] or not isinstance(review['evidence'], list) or any(not text(e) for e in review['evidence']):
                        raise ValueError('Invalid evaluation criterion or evidence')
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError('Malformed evaluation results.json') from error
    return value

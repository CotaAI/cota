"""Normalize visible review evidence against fixed required/advisory criteria."""
import json
import re

_NUMBERED = re.compile(r'^\s*(\d+)[.)、．]\s*(.+)$', re.MULTILINE)
_ADVICE = re.compile(r'^(?:\[(?:advice|optional)\]|【(?:建议|可选)】|(?:建议|可选)[:：])', re.I)


def assess(text, criteria):
    """Invalid/incomplete prose is uncertainty; never an implicit approval."""
    uncertain = {'verdict': 'uncertain', 'checks': [],
                 'note': 'No complete structured assessment; inspect the saved original response.'}
    numbered = _NUMBERED.findall(criteria)
    expected = {identifier: 'advice' if _ADVICE.match(value.strip()) else 'required'
                for identifier, value in numbered} if numbered else {'overall': 'required'}
    if len(expected) > 64 or len(expected) != (len(numbered) if numbered else 1):
        return uncertain
    value = text.strip()
    if value.startswith('```json\n') and value.endswith('```'):
        value = value[8:-3].strip()
    try:
        result = json.loads(value)
        checks = result['checks']
        if not isinstance(checks, list) or len(checks) != len(expected):
            return uncertain
        normalized = {}
        for check in checks:
            identifier = str(check['id'])
            status, evidence = check['status'], check['evidence']
            if (identifier not in expected or identifier in normalized or status not in ('pass', 'fail', 'uncertain')
                    or not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 4000):
                return uncertain
            normalized[identifier] = {'id': identifier, 'status': status,
                                      'severity': expected[identifier], 'evidence': evidence.strip()}
    except (ValueError, TypeError, KeyError):
        return uncertain
    ordered = [normalized[identifier] for identifier in expected]
    required = [check['status'] for check in ordered if check['severity'] == 'required']
    verdict = ('revise' if 'fail' in required else 'uncertain'
               if not required or 'uncertain' in required or result.get('verdict') == 'uncertain' else 'pass')
    return {'verdict': verdict, 'checks': ordered}

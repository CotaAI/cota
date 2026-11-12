"""Required checks decide acceptance; advice and unstructured claims do not."""
import importlib
import json

import httpx
import pytest

from tests.test_picture_book_bot import book_modules as book_modules, book_root as book_root, image_bytes


@pytest.fixture
def assess(book_modules):
    return importlib.import_module('bookbot.review_checks').assess


def checked(identifier, status='pass', severity='required'):
    return {'id': identifier, 'status': status, 'severity': severity, 'evidence': 'Specific visible observation.'}


def test_required_failure_cannot_be_downgraded_to_advice_by_the_model(assess):
    text=json.dumps({'verdict':'pass','checks':[checked('1','fail','advice'),checked('2')]})
    result=assess(text,'1. Text must be readable.\n2. The child is visible.')
    assert result['verdict']=='revise'
    assert result['checks'][0]['severity']=='required'


def test_optional_aesthetic_feedback_does_not_reject_a_passing_page(assess):
    result=assess(json.dumps({'verdict':'revise','checks':[checked('1'),checked('2','fail')]}),
                  '1. Text is readable.\n2. [advice] Prefer a warmer background.')
    assert result['verdict']=='pass'
    assert result['checks'][1]['severity']=='advice'


@pytest.mark.parametrize('text', ['Looks perfect.', '{"verdict":"pass","checks":[]}',
    json.dumps({'verdict':'pass','checks':[checked('1')]}),
    json.dumps({'verdict':'pass','checks':[checked('1'),checked('1')]}),
    json.dumps({'verdict':'pass','checks':[{'id':'1','status':'pass','evidence':''},checked('2')]}),
])
def test_incomplete_or_unstructured_reports_remain_uncertain(assess,text):
    result=assess(text,'1. Text readable.\n2. Character visible.')
    assert result['verdict']=='uncertain'


def test_numbered_checks_are_complete_and_sorted_like_fixed_criteria(assess):
    result=assess(json.dumps({'verdict':'pass','checks':[checked('2'),checked('1')]}),
                  '1. Text readable.\n2. Character visible.')
    assert result['verdict']=='pass'
    assert [c['id'] for c in result['checks']]==['1','2']


def test_explicit_uncertainty_is_not_turned_into_acceptance(assess):
    result=assess(json.dumps({'verdict':'uncertain','checks':[checked('overall')]}),'Check the visible ears.')
    assert result['verdict']=='uncertain'


def test_valid_fenced_json_and_plain_criteria(assess):
    payload=json.dumps({'verdict':'pass','checks':[checked('overall')]})
    assert assess('```json\n'+payload+'\n```','Check the visible ears.')['verdict']=='pass'


def test_review_saves_assessment_without_approving_book_flags(book_modules,book_root):
    root,project=book_root
    (project/'criteria.txt').write_text('1. Text readable.\n2. [advice] Prefer a warmer background.')
    (project/'page.png').write_bytes(image_bytes())
    payload=json.dumps({'verdict':'revise','checks':[checked('1'),checked('2','fail')]})
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
        'choices':[{'message':{'content':payload}}]}))) as client:
        report=book_modules['models'].review(root,project,'criteria.txt',['page.png'],'review.json',asset='pdf-face-01',client=client)
    assert report['assessment']['verdict']=='pass'
    assert json.loads((project/'review.json').read_text())['assessment']==report['assessment']
    assert 'qa' not in report and not (project/'book.json').exists()

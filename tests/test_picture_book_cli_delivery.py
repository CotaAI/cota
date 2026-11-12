"""Small truthful command results; large evidence remains in saved files."""
import hashlib
import json
import subprocess
import sys

import httpx

from tests.test_picture_book_bot import book_modules as book_modules, book_root as book_root, image_bytes
from tests.test_picture_book_convergence import cli_copy


def test_review_cli_is_compact_with_saved_evidence_and_opt_in_full_output(book_modules,book_root):
    root,project=book_root
    (project/'criteria.txt').write_text('1. The ears are visible.')
    (project/'page.png').write_bytes(image_bytes())
    text=json.dumps({'verdict':'pass','checks':[{'id':'1','status':'pass','severity':'required','evidence':'Two ears visible.'}]})
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
        'choices':[{'message':{'content':text}}]}))) as client:
        book_modules['models'].review(root,project,'criteria.txt',['page.png'],'review.json',asset='pdf-face-01',client=client)
    script=cli_copy(root)
    args=[sys.executable,str(script),'--project','example','review','--asset','pdf-face-01',
          '--prompt','criteria.txt','--image','page.png','--output','review.json']
    result=subprocess.run(args,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    compact=json.loads(result.stdout)
    assert compact['verdict']=='pass' and compact['reused'] is True
    assert 'content' not in compact and 'prompt' not in compact
    assert len(result.stdout.splitlines())==1
    evidence=project/compact['evidence']['path']
    assert hashlib.sha256(evidence.read_bytes()).hexdigest()==compact['evidence']['sha256']
    full=subprocess.run([*args,'--full'],capture_output=True,text=True,timeout=15)
    assert full.returncode==0,full.stderr
    assert json.loads(full.stdout)['content']==text


def test_draft_deliverables_check_actual_byte_limit_before_sending(book_root):
    root,project=book_root
    for name in ('book.pdf','previews/overview.jpg','previews/covers.png','打印说明.md'):
        path=project/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'artifact')
    with (project/'book.pdf').open('r+b') as stream:stream.truncate(20*1024*1024+85085)
    script=cli_copy(root)
    result=subprocess.run([sys.executable,str(script),'--project','example','deliverables','--draft'],
                          capture_output=True,text=True,timeout=15)
    assert result.returncode==1
    error=json.loads(result.stderr)
    assert error['retryable'] is False and error['max_file_bytes']==20*1024*1024
    assert error['actual_bytes']==20*1024*1024+85085
    assert error['file']=='book.pdf'


def test_explicit_channel_limit_is_used_for_draft_preflight(book_root):
    root,project=book_root
    for name in ('book.pdf','previews/overview.jpg','previews/covers.png','打印说明.md'):
        path=project/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'artifact')
    with (project/'book.pdf').open('r+b') as stream:stream.truncate(5000)
    script=cli_copy(root)
    result=subprocess.run([sys.executable,str(script),'--project','example','deliverables','--draft','--max-file-bytes','4096'],
                          capture_output=True,text=True,timeout=15)
    assert result.returncode==1
    error=json.loads(result.stderr)
    assert error['max_file_bytes']==4096 and error['actual_bytes']==5000

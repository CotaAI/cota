#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "Pillow>=10,<13",
#     "reportlab>=4,<5",
#     "pypdf>=5,<7",
#     "httpx>=0.27",
#     "pyyaml>=6",
# ]
# ///
"""Small commands used by Pi; this program never selects a Skill or runs an Agent."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bookbot.common import model_config, project_path, read_json, sha256  # noqa: E402

SKILL = ROOT / 'skills/creating-childrens-picture-books'


def doctor():
    from bookbot.layout import font_path
    modules = {name: importlib.util.find_spec(module) is not None for name, module in
               [('Pillow', 'PIL'), ('ReportLab', 'reportlab'), ('pypdf', 'pypdf')]}
    models = {}
    for kind in ('image', 'vision'):
        try:
            config = model_config(ROOT, kind)
            models[kind] = {'configured': True, 'model': config['model']}
        except ValueError:
            models[kind] = {'configured': False}
    try:
        font = str(font_path(ROOT))
    except ValueError:
        font = None
    poppler = shutil.which('pdftoppm') is not None
    return {'python': sys.executable, 'dependencies': modules, 'pdftoppm': poppler, 'font': font,
            'models': models, 'ready': all(modules.values()) and poppler and bool(font)
            and all(model['configured'] for model in models.values()),
            'note': 'Configuration check only; reference-image/sample-page verification still required'}


def compact_result(command, result, project, args):
    """Keep command stdout complete and small; retain full evidence on disk."""
    if command == 'review':
        from bookbot.review_checks import assess
        assessment = result.get('assessment') or assess(result['content'], result['prompt'])
        report = project_path(ROOT, args.project) / args.output
        verdict = assessment['verdict']
        return {'asset': result['asset'], 'verdict': verdict, 'reused': result.get('reused', False),
                'checks_passed': sum(c['status'] == 'pass' for c in assessment['checks']),
                'issues': [c for c in assessment['checks'] if c['status'] != 'pass'],
                'image_inputs': result['image_inputs'],
                **({'current_image_inputs': result['current_image_inputs']} if result.get('current_image_inputs') else {}),
                'evidence': {'path': args.output, 'sha256': sha256(report.read_bytes())},
                'next': ('Preserve this version and continue independent work' if verdict == 'pass' else
                         'Address only required failures within the remaining page revision budget' if verdict == 'revise' else
                         'Preserve this version and report uncertainty; do not request another verdict for the same bytes')}
    if command == 'generate':
        fields = ('asset', 'attempt', 'status', 'output', 'input_hash', 'sha256', 'reused', 'reused_from')
        journal = Path(result['output']).with_suffix('.request.json')
        return {**{key: result[key] for key in fields if key in result},
                'evidence': {'path': str(journal), 'sha256': sha256((project / journal).read_bytes())}}
    if command == 'status':
        return {**{key: value for key, value in result.items() if key not in ('images', 'requests')},
                'image_count': len(result['images']), 'request_count': len(result['requests'])}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Use uv run for automatic dependency isolation (PEP 723).
Invoke this script by its absolute path from any directory; do not guess ../ levels.
The examples below use paths relative to the Bot root, for manual use there only.
Project commands place --project BEFORE the command:
  uv run scripts/book.py doctor
  uv run scripts/book.py init my-book
  uv run scripts/book.py --project my-book generate --help
  uv run scripts/book.py --project my-book build --help

Scripts read endpoints.yml themselves; never put credentials in command arguments.
doctor checks configuration/dependencies only and makes no paid model requests.
Network requests have a 240-second limit; allow up to 300 seconds for the Bash tool.
Use command --help for detailed file, layout and review requirements.
Run commands directly: do not pipe through tail/head or append a successful echo.
Such shell commands can hide a failed program exit. Read the JSON and exit status.

Normal workflow (no implementation-source reading required):
  1. doctor once, then init; save the brief, story, storyboard and visual rules.
  2. Use image_generate with actual reference files for character art and a sample.
  3. Use image_understand for visual checks; save fixed numbered criteria first.
     Import its successful call with review --tool-call-id (see review --help).
     read is for files, not a substitute for formal visual review.
  4. Generate remaining art with image_generate; fill book.json using build --help.
  5. build, inspect every rendered page, validate, then deliverables.
Read only the help needed for the current step. For an existing project, status
comes first; completed generation journals allow reuse without another paid call.
Always keep --asset stable across revision filenames. Each asset allows one initial
image and two revisions; renamed files/session restarts do not reset that budget.
retryable=false means stop retrying that asset and continue independent work.
Rendered PDF faces also have one baseline plus two visual revisions, including
local image edits. Read status.rendering; accepted versions stay frozen.
Normal stdout is complete compact JSON; use --full only for detailed saved fields.
Do not change asset/project/criteria to bypass limits; report unresolved work.''')
    parser.add_argument('--project', help='Name inside workspace/books, or an absolute path inside it; required except for doctor/init')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor', help='Check configuration and local dependencies without model requests')
    init = commands.add_parser('init', help='Create a project from the generic Skill template; does not write a story')
    init.add_argument('name', help='New project name inside workspace/books')
    commands.add_parser('status', help='Inspect saved project, review flags and generation journals before continuing')
    generate = commands.add_parser('generate', help='Generate one PNG, or edit using actual reference images',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Paths are relative to the project; absolute in-project paths also work.
Write the UTF-8 prompt file first (1-32000 characters). Request one image at a time.
Without --reference, generate a new image. Repeat --reference for up to eight real
PNG/JPEG/WebP inputs (each <=32 MiB); Qwen Image 3.0 allows at most three, each
<=10 MiB, <=8000 pixels per side and <=10:1 aspect ratio. For an edit, include the original image and
describe the specific change; a filename in prompt text is not an image input.

Output must end in .png. image.api=openai (default) uses multipart edits and requires
inline b64_json. image.api=qwen uses JSON generations for both new art and reference
edits; returned URLs are downloaded only from approved HTTPS download_hosts (default
*.aliyuncs.com), without API Authorization or redirects, up to 32 MiB. No signed URL
is retained in errors or journals. The adjacent .request.json retains hashes and request status without
credentials/base64. Identical completed output is reused; changed input needs a new
revision filename. A started request has an unknown outcome: inspect provider history,
never blindly retry it. Unknown outcomes block further requests for that asset.
Identical completed inputs reuse saved bytes, even under a new output filename.
Only three paid attempts per stable --asset: one initial image and two revisions.
Keep confirmed assets stable; exhausted/uncertain assets must be reported without
falsely setting QA to passed. Generate artwork without final Chinese text.''')
    generate.add_argument('--asset', required=True, help='Stable page/cover ID, unchanged across revision filenames; max 1 initial + 2 revisions')
    generate.add_argument('--prompt', required=True, help='UTF-8 prompt file, relative to project')
    generate.add_argument('--output', required=True, help='PNG output, relative to project')
    generate.add_argument('--reference', action='append', default=[], help='Actual image file, relative to project; repeatable')
    review = commands.add_parser('review', help='Verify and save an actual image_understand observation; no model request',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''First call image_understand with the target image and the exact prompt file text.
Then pass its returned source tool_call_id here. This command only imports committed
successful tool evidence from this Bot SQLite Store; it does not call a model.
All paths stay inside the project. Use one --image for the actual target PNG/JPEG/WebP,
<=32 MiB. A read result or main-model opinion is not formal visual review evidence.
Review every rendered page, not only a small contact sheet. Output must end in .json.
Use a stable --asset target (e.g. page-04 for artwork, pdf-face-05 for a rendered
PDF face). Fixed criteria belong to that target: keep the prompt file content stable,
put the actual target version path only in --image. Filename
changes do not create new review criteria. Do not alter criteria to seek approval.
Name the stable target in the fixed criteria; supply its actual version path
through --image. Do not reuse another page's questions. The saved report links
image_inputs and the actual tool result. Review only the requested visible
criteria and verify the specific correction on the new version.
Identical criteria and image bytes reuse one canonical observation, even with new
output names or byte-identical image aliases. image_inputs remains the original
service evidence; current_image_inputs maps aliases when reused. Canonical evidence
is in .bookbot/reviews; do not edit/remove it to obtain another verdict. Conflicting
manual observations are uncertain, not permission to keep rerolling the image.
Changed pixels need a new review output filename; changed criteria require a
separate user-requested production task rather than silently resetting this one.
The report is evidence, not automatic QA approval. Correct issues and record the
actual language/content/visual review before updating book.json qa flags.
Write numbered criteria (1. ... / 2. ...); all are required unless prefixed
[advice] or [optional]. The model returns one evidence-backed check per criterion.
Verdicts: pass, revise (required failure), uncertain (missing/unclear evidence).
Advice never blocks acceptance. Invalid/unstructured replies remain uncertain;
do not repeatedly ask the same image for a different verdict.
Use pdf-face-01 etc. for final rendered faces. A canonical required-check pass
freezes that exact page version; it does not automatically approve the whole book.''')
    review.add_argument('--asset', required=True, help='Stable review target; e.g. page-04 or pdf-face-05. Criteria are fixed on its first review')
    review.add_argument('--prompt', required=True, help='UTF-8 review instructions file, relative to project')
    review.add_argument('--image', action='append', required=True, help='One actual review target; same image_path used by image_understand')
    review.add_argument('--output', required=True, help='Review JSON path, relative to project')
    review.add_argument('--tool-call-id', required=True, help='Import a committed image_understand result from this Bot SQLite Store; makes no model request. '
        'Use one --image and the exact prompt sent to the tool. The returned tool source contains its call ID')
    build = commands.add_parser('build', help='Lay out Chinese text and render every PDF page',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Fill book.json using the generic Skill project manifest. pages must contain every
PDF face in consecutive 1-based order, including structural blank faces; page_count
must match. format.width_mm/height_mm define the physical page size.

This renderer uses explicit page layout (millimetres from the top-left; fonts in points):
{
  "page": 5, "role": "story", "layout": "integrated-single-page",
  "asset": "illustrations/finals/page-01.png",
  "image_box": [10, 10, 190, 90],
  "image_fit": "contain",
  "text_elements": [
    {"text": "小兔抬头，云朵轻轻飘过。", "box": [10, 110, 190, 25], "font_size": 18,
     "align": "left", "fill": "#1f1f29"}
  ]
}

Each box is [left, top, width, height] within the page. Asset paths are relative to
the project. Place all visible text in text_elements, not the legacy page text field.
Text supports only text, box, font_size (8-72 pt), align (left/center/right) and
fill (#RRGGBB). Defaults: 18 pt, left, #1f1f29. Bold/weight, custom line spacing,
background panels and image_path are unsupported and rejected, not ignored.
Page fields: page, role, title, text, blank, blank_reason, layout, asset, image_box, image_fit,
text_elements, context_asset, detail_asset, arrow_count, notes. title/role/layout/
notes and context/detail fields are metadata/evidence, not extra drawing commands.
page text must be absent/empty; only text_elements are drawn. page is the 1-based
PDF face number including blanks; do not confuse it with a Python list index or
the artwork filename. Unknown page/text fields fail before outputs are replaced.
Choose positions for each illustration; do not force one layout on the whole book.
image_fit=contain (default) preserves the whole image and may leave margins;
cover fills the box with a deterministic central crop. Use these instead of
ad-hoc Pillow background extension or repeated colour-band editing.
Wordless pages can omit text_elements; blank pages must have no artwork or text.
Keep the Skill's required context_asset/detail_asset/arrow_count evidence for any
context-to-detail scene. The composed illustration remains the page asset.

Output: book.pdf, previews/pages/*.png (including blanks), previews/overview.jpg,
previews/covers.png, 打印说明.md, deliverables and sheet_map in book.json.
Chinese fonts are embedded; missing glyphs and overflowing boxes are errors.
Changed pages invalidate affected QA domains (see invalidated_checks); metadata-only
notes/printing corrections do not reset visual reviews or rerender pages. Review actual rendered
pages, complete language/content checks, then update QA and run validate. build does
not approve a book. Physical proof remains print_tested=false until really tested.
Successful build returns input_hash and manifest. Unchanged inputs with intact PDF,
previews and instructions return reused=true without rendering again; damaged or
missing outputs are repaired without charging a visual revision; affected PDF QA is cleared.
Each PDF face allows one baseline plus two visual revisions, including local image,
text and layout edits; accepted current versions are frozen. Check changed_pages,
pending_pages and status.rendering. Metadata edits do not spend this budget.
Print images use <=240dpi JPEG derivatives; original art and vector text remain intact.
Use --max-file-bytes with the receiving send_files limit. All delivery files are
preflighted before replacing the prior package. Printing instructions/sheet count
are generated from book.json; edit the manifest, not generated output files.
Never set QA merely to make validate pass.''')
    build.add_argument('--max-file-bytes', type=int, default=20 * 1024 * 1024,
                       help='Actual per-file delivery limit; default 20 MiB, checked before replacing outputs')
    commands.add_parser('validate', help='Require the current render and run the original Skill package validator',
        description='Reject stale source/PDF/deliverable hashes before checking the generic Skill contract. '
                    'Validation checks structure and declared evidence, not actual visual quality.')
    deliverables = commands.add_parser('deliverables', help='List verified file paths for normal conversation attachment delivery',
        description='Validate the current digital package, then return absolute paths for send_files. '
                    'Only use --draft for an explicitly unapproved review copy. Caption drafts honestly; '
                    'successful send_files means committed, not confirmed receipt. Never attach credentials or databases.')
    deliverables.add_argument('--draft', action='store_true', help='List files for an explicitly unapproved review copy')
    deliverables.add_argument('--max-file-bytes', type=int, default=20 * 1024 * 1024,
                              help='Per-file limit advertised by send_files; draft files are checked too')
    for command_parser in commands.choices.values():
        command_parser.add_argument('--full', action='store_true', help='Show full saved fields instead of compact command JSON')
    args = parser.parse_args(argv)
    project = None
    if args.command == 'doctor':
        result = doctor()
    else:
        project = project_path(ROOT, args.name if args.command == 'init' else args.project)
        if args.command == 'init':
            project.mkdir(parents=True, exist_ok=True)
            if not (project / 'book.json').exists():
                shutil.copytree(SKILL / 'assets/project-template', project, dirs_exist_ok=True)
            result = {'project': str(project), 'manifest': str(project / 'book.json')}
        elif args.command == 'status':
            from bookbot.production import production_status
            from bookbot.render_state import render_status
            data = read_json(project / 'book.json')
            result = {'project': str(project), 'title': data.get('title'), 'qa': data.get('qa'),
                      'production': production_status(project), 'rendering': render_status(project),
                      'render_input_hash': data.get('render_input_hash'),
                      'pages': [{key: page.get(key) for key in ('page', 'role', 'blank', 'asset')}
                                for page in data.get('pages', [])],
                      'images': [str(p.relative_to(project)) for p in project.rglob('*.png')],
                      'requests': [{'path': str(p.relative_to(project)), 'status': read_json(p).get('status')}
                                   for p in project.rglob('*.request.json')]}
        elif args.command == 'generate':
            from bookbot.models import generate
            result = generate(ROOT, project, args.prompt, args.output, asset=args.asset, references=args.reference)
        elif args.command == 'review':
            from bookbot.tool_reviews import record_review
            result = record_review(ROOT, project, args.prompt, args.image, args.output,
                                   asset=args.asset, tool_call_id=args.tool_call_id)
        elif args.command == 'build':
            from bookbot.layout import build
            result = build(ROOT, project, max_file_bytes=args.max_file_bytes)
        else:
            if args.command == 'deliverables':
                from bookbot.layout import delivery_status
                delivery = delivery_status(project, max_file_bytes=args.max_file_bytes)
            if args.command == 'validate' or not args.draft:
                from bookbot.layout import require_current_render
                require_current_render(ROOT, project)
                from bookbot.tool_reviews import require_visual_reviews
                require_visual_reviews(project)
                checked = subprocess.run([sys.executable, str(SKILL / 'scripts/validate_book_package.py'), str(project)],
                                         capture_output=True, text=True, timeout=60)
                result = {'valid': checked.returncode == 0, 'details': checked.stdout.strip()}
                if args.command == 'validate' or checked.returncode:
                    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
                    return 0 if result['valid'] else 1
            from bookbot.layout import DELIVERABLES
            from bookbot.common import confined
            paths = [confined(project, path) for path in dict.fromkeys(DELIVERABLES.values())]
            if any(not path.is_file() for path in paths):
                raise ValueError('Build the complete digital package before listing deliverables')
            result = {'status': 'draft' if args.draft else 'validated-digital-package',
                      'delivery': delivery, 'paths': [str(path) for path in paths], 'next': 'Use send_files to attach these files to the current conversation'}
    if not args.full:
        result = compact_result(args.command, result, project, args)
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, ImportError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error), **getattr(error, 'details', {})}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

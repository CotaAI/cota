#!/usr/bin/env python3
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

from bookbot.common import model_config, project_path, read_json  # noqa: E402

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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Use the Python executable and Bot directory advertised by the runtime.
Invoke this script by its absolute path from any directory; do not guess ../ levels.
The examples below use paths relative to the Bot root, for manual use there only.
Project commands place --project BEFORE the command:
  python scripts/book.py doctor
  python scripts/book.py init my-book
  python scripts/book.py --project my-book generate --help
  python scripts/book.py --project my-book build --help

Scripts read endpoints.yml themselves; never put credentials in command arguments.
doctor checks configuration/dependencies only and makes no paid model requests.
Network requests have a 240-second limit; allow up to 300 seconds for the Bash tool.
Use command --help for detailed file, layout and review requirements.
Run commands directly: do not pipe through tail/head or append a successful echo.
Such shell commands can hide a failed program exit. Read the JSON and exit status.

Normal workflow (no implementation-source reading required):
  1. doctor once, then init; save the brief, story, storyboard and visual rules.
  2. Read generate --help; write a prompt file, generate a character reference.
  3. Inspect the actual image with read or review; generate and check one sample page.
  4. Generate remaining art with --reference; fill book.json using build --help.
  5. build, inspect every rendered page, validate, then deliverables.
Read only the help needed for the current step. For an existing project, status
comes first; completed generation journals allow reuse without another paid call.''')
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
never blindly retry it. Generate artwork without final Chinese text.''')
    generate.add_argument('--prompt', required=True, help='UTF-8 prompt file, relative to project')
    generate.add_argument('--output', required=True, help='PNG output, relative to project')
    generate.add_argument('--reference', action='append', default=[], help='Actual image file, relative to project; repeatable')
    review = commands.add_parser('review', help='Review actual images and save the observations as JSON',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''All paths stay inside the project. Repeat --image for 1-8 actual PNG/JPEG/WebP
images, each <=32 MiB. Include the character reference when checking continuity.
Review every rendered page, not only a small contact sheet. Output must end in .json.
Each --image must have its own flag. Name the target page/path and the reference
path in the prompt; do not rely only on "image 1/image 2" or reuse another page's
questions. The service receives labels/hashes next to the actual images; the saved
report includes image_inputs in the same order. Review only the requested visible
criteria and verify the specific correction on the new version.
Identical reviews are reused; changed inputs need a new revision filename.
The report is evidence, not automatic QA approval. Correct issues and record the
actual language/content/visual review before updating book.json qa flags.''')
    review.add_argument('--prompt', required=True, help='UTF-8 review instructions file, relative to project')
    review.add_argument('--image', action='append', required=True, help='Actual image file; repeat for up to eight images')
    review.add_argument('--output', required=True, help='Review JSON path, relative to project')
    commands.add_parser('build', help='Lay out Chinese text and render every PDF page',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Fill book.json using the generic Skill project manifest. pages must contain every
PDF face in consecutive 1-based order, including structural blank faces; page_count
must match. format.width_mm/height_mm define the physical page size.

This renderer uses explicit page layout (millimetres from the top-left; fonts in points):
{
  "page": 5, "role": "story", "layout": "integrated-single-page",
  "asset": "illustrations/finals/page-01.png",
  "image_box": [10, 10, 190, 90],
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
Page fields: page, role, title, text, blank, blank_reason, layout, asset, image_box,
text_elements, context_asset, detail_asset, arrow_count, notes. title/role/layout/
notes and context/detail fields are metadata/evidence, not extra drawing commands.
page text must be absent/empty; only text_elements are drawn. page is the 1-based
PDF face number including blanks; do not confuse it with a Python list index or
the artwork filename. Unknown page/text fields fail before outputs are replaced.
Choose positions for each illustration; do not force one layout on the whole book.
Wordless pages can omit text_elements; blank pages must have no artwork or text.
Keep the Skill's required context_asset/detail_asset/arrow_count evidence for any
context-to-detail scene. The composed illustration remains the page asset.

Output: book.pdf, previews/pages/*.png (including blanks), previews/overview.jpg,
previews/covers.png, 打印说明.md, deliverables and sheet_map in book.json.
Chinese fonts are embedded; missing glyphs and overflowing boxes are errors.
Changes to text, artwork, layout or font clear prior QA flags. Review actual rendered
pages, complete language/content checks, then update QA and run validate. build does
not approve a book. Physical proof remains print_tested=false until really tested.
Successful build returns input_hash and manifest. Unchanged inputs with intact PDF,
previews and instructions return reused=true without rendering again; damaged or
missing outputs are rebuilt and QA is cleared. Inspect the changed page rather than
repeatedly rebuilding unchanged sources. Never set QA merely to make validate pass.''')
    commands.add_parser('validate', help='Require the current render and run the original Skill package validator',
        description='Reject stale source/PDF/deliverable hashes before checking the generic Skill contract. '
                    'Validation checks structure and declared evidence, not actual visual quality.')
    deliverables = commands.add_parser('deliverables', help='List verified file paths for normal conversation attachment delivery',
        description='Validate the current digital package, then return absolute paths for send_files. '
                    'Only use --draft for an explicitly unapproved review copy. Caption drafts honestly; '
                    'successful send_files means committed, not confirmed receipt. Never attach credentials or databases.')
    deliverables.add_argument('--draft', action='store_true', help='List files for an explicitly unapproved review copy')
    args = parser.parse_args(argv)
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
            data = read_json(project / 'book.json')
            result = {'project': str(project), 'title': data.get('title'), 'qa': data.get('qa'),
                      'render_input_hash': data.get('render_input_hash'),
                      'pages': [{key: page.get(key) for key in ('page', 'role', 'blank', 'asset')}
                                for page in data.get('pages', [])],
                      'images': [str(p.relative_to(project)) for p in project.rglob('*.png')],
                      'requests': [{'path': str(p.relative_to(project)), 'status': read_json(p).get('status')}
                                   for p in project.rglob('*.request.json')]}
        elif args.command == 'generate':
            from bookbot.models import generate
            result = generate(ROOT, project, args.prompt, args.output, references=args.reference)
            # Prompt is saved in the project, not repeated in a long tool result.
            result.pop('prompt', None)
        elif args.command == 'review':
            from bookbot.models import review
            result = review(ROOT, project, args.prompt, args.image, args.output)
            result.pop('prompt', None)
        elif args.command == 'build':
            from bookbot.layout import build
            result = build(ROOT, project)
        else:
            if args.command == 'validate' or not args.draft:
                from bookbot.layout import require_current_render
                require_current_render(ROOT, project)
                checked = subprocess.run([sys.executable, str(SKILL / 'scripts/validate_book_package.py'), str(project)],
                                         capture_output=True, text=True, timeout=60)
                result = {'valid': checked.returncode == 0, 'details': checked.stdout.strip()}
                if args.command == 'validate' or checked.returncode:
                    print(json.dumps(result, ensure_ascii=False))
                    return 0 if result['valid'] else 1
            from bookbot.layout import DELIVERABLES
            from bookbot.common import confined
            paths = [confined(project, path) for path in dict.fromkeys(DELIVERABLES.values())]
            if any(not path.is_file() for path in paths):
                raise ValueError('Build the complete digital package before listing deliverables')
            result = {'status': 'draft' if args.draft else 'validated-digital-package',
                      'paths': [str(path) for path in paths], 'next': 'Use send_files to attach these files to the current conversation'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, ImportError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

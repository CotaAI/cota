#!/usr/bin/env python3
"""Validate a children's picture-book package from its book.json manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


MM_PER_PT = 25.4 / 72
REQUIRED_DELIVERABLES = (
    "reading_pdf",
    "home_print_pdf",
    "printing_instructions",
    "full_preview",
    "cover_back_preview",
)
VALID_PAGE_ROLES = {
    "cover",
    "inside-cover",
    "title",
    "copyright",
    "story",
    "activity",
    "ending",
    "inside-back-cover",
    "back-cover",
    "blank",
}


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"ERROR: missing manifest: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: invalid JSON in {path}: {exc}")


def add_path_check(root: Path, value, label, errors):
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} is empty")
        return
    if not (root / value).exists():
        errors.append(f"{label} does not exist: {value}")


def inspect_pdf(root: Path, relative: str, expected_pages: int, width_mm: float, height_mm: float, errors, warnings):
    if not relative or not (root / relative).exists():
        return
    try:
        from pypdf import PdfReader
    except ImportError:
        warnings.append("pypdf unavailable; skipped PDF page-count and size inspection")
        return

    reader = PdfReader(str(root / relative))
    if len(reader.pages) != expected_pages:
        errors.append(f"{relative}: PDF has {len(reader.pages)} pages; manifest says {expected_pages}")
    if reader.pages:
        page = reader.pages[0]
        actual_w = float(page.mediabox.width) * MM_PER_PT
        actual_h = float(page.mediabox.height) * MM_PER_PT
        if abs(actual_w - width_mm) > 0.8 or abs(actual_h - height_mm) > 0.8:
            errors.append(
                f"{relative}: first page is {actual_w:.1f}×{actual_h:.1f} mm; "
                f"manifest says {width_mm:.1f}×{height_mm:.1f} mm"
            )


def inspect_separate_profile(root, data, pages, errors, warnings):
    printing = data.get("printing") or {}
    if printing.get("profile") != "separate-covers-title":
        return
    count = len(pages)
    if count < 8 or count % 2:
        errors.append("separate-covers-title needs an even page_count of at least 8")
        return
    if printing.get("sheets") != count // 2:
        errors.append("printing.sheets does not match physical page pairs")
    for index, role in [(1, "inside-cover"), (count - 2, "inside-back-cover")]:
        if pages[index].get("role") != role or pages[index].get("blank") is not True:
            errors.append(f"{role} must be a blank physical face")
    if pages[2].get("role") != "title":
        errors.append("independent title must be PDF page 3")
    if printing.get("title_single_sided") is not True:
        warnings.append("custom duplex title: manually review title/body job mapping")
        return
    if pages[3].get("blank") is not True or pages[3].get("role") != "blank":
        errors.append("title verso must be a blank page")
    for p in pages:
        if p.get("blank") and any(p.get(k) for k in ("text", "lines", "text_elements", "asset")):
            errors.append(f"page {p.get('page')}: blank page must not have text or artwork")
    expected = [([1], "simplex", 1), ([3], "simplex", 1),
                (list(range(5, count - 1)), "duplex", (count - 6) // 2),
                ([count], "simplex", 1)]
    jobs = printing.get("jobs") or []
    if not jobs and printing.get("delivery_mode") == "single-pdf":
        expected = []
    elif len(jobs) != 4:
        errors.append("printing.jobs must contain front, title, body, back jobs")
        return
    fmt = data.get("format") or {}
    for job, (source_pages, mode, sheets) in zip(jobs, expected):
        if job.get("source_pages") != source_pages:
            errors.append("print job source_pages mismatch")
        if job.get("mode") != mode:
            errors.append("print job mode mismatch")
        if job.get("sheets") != sheets:
            errors.append("print job sheets mismatch")
        add_path_check(root, job.get("file"), "printing.jobs.file", errors)
        inspect_pdf(root, job.get("file"), len(source_pages),
                    job.get("width_mm", fmt.get("width_mm", 0)),
                    job.get("height_mm", fmt.get("height_mm", 0)), errors, warnings)
    # Rendering remains necessary: text/image checks cannot detect all drawn marks.
    try:
        from pypdf import PdfReader
        rel = (data.get("deliverables") or {}).get("home_print_pdf")
        if rel and (root / rel).exists():
            pdf = PdfReader(root / rel)
            for i, p in enumerate(pages):
                if p.get("blank") and i < len(pdf.pages):
                    if (pdf.pages[i].extract_text() or "").strip() or len(pdf.pages[i].images):
                        errors.append(f"page {i + 1}: blank PDF face contains text/images")
    except ImportError:
        warnings.append("pypdf unavailable; blank PDF faces not inspected")


def validate(root: Path):
    data = load_json(root / "book.json")
    errors = []
    warnings = []

    for key in ("title", "audience_age", "book_type", "language", "binding"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append(f"missing or empty field: {key}")

    page_count = data.get("page_count")
    if not isinstance(page_count, int) or page_count <= 0:
        errors.append("page_count must be a positive integer")
        page_count = 0

    pages = data.get("pages")
    if not isinstance(pages, list):
        errors.append("pages must be a list")
        pages = []
    if page_count and len(pages) != page_count:
        errors.append(f"pages has {len(pages)} entries; page_count is {page_count}")

    if pages:
        numbers = [page.get("page") for page in pages]
        if numbers != list(range(1, len(pages) + 1)):
            errors.append("page numbers must be consecutive, starting at 1")
        roles = [page.get("role") for page in pages]
        invalid = sorted({role for role in roles if role not in VALID_PAGE_ROLES})
        if invalid:
            errors.append(f"invalid page roles: {', '.join(map(str, invalid))}")
        if roles[0] != "cover":
            errors.append("first page role must be cover")
        if roles[-1] != "back-cover":
            errors.append("last page role must be back-cover")
        layouts = [page.get("layout") for page in pages if page.get("role") not in {"cover", "back-cover"}]
        if len(layouts) >= 6 and len(set(layouts)) == 1:
            warnings.append("all content pages use one layout; review for mechanical repetition")

        for page in pages:
            if page.get("layout") == "context-to-detail":
                if page.get("arrow_count") != 1:
                    errors.append(f"page {page.get('page')}: context-to-detail requires arrow_count=1")
                for key in ("context_asset", "detail_asset"):
                    add_path_check(root, page.get(key), f"page {page.get('page')} {key}", errors)
            elif page.get("asset"):
                add_path_check(root, page.get("asset"), f"page {page.get('page')} asset", errors)

    if data.get("binding") == "saddle-stitch" and page_count % 4:
        errors.append("saddle-stitch page_count must be a multiple of 4")

    fmt = data.get("format") or {}
    try:
        width_mm = float(fmt["width_mm"])
        height_mm = float(fmt["height_mm"])
    except (KeyError, TypeError, ValueError):
        errors.append("format.width_mm and format.height_mm must be numbers")
        width_mm = height_mm = 0
    if fmt.get("paper") in {"A4", "A5"} and fmt.get("requires_trimming") is True:
        warnings.append("standard paper is marked as requiring trimming; confirm this is intentional")
    if fmt.get("paper") == "custom" and fmt.get("requires_trimming") is False:
        warnings.append("custom size is marked no-trim; confirm printer supports that exact stock")

    deliverables = data.get("deliverables") or {}
    for key in REQUIRED_DELIVERABLES:
        add_path_check(root, deliverables.get(key), f"deliverables.{key}", errors)
    if (data.get("printing") or {}).get("professional"):
        add_path_check(root, deliverables.get("professional_print_pdf"), "deliverables.professional_print_pdf", errors)

    if page_count and width_mm and height_mm:
        for key in ("reading_pdf", "home_print_pdf"):
            relative = deliverables.get(key)
            if isinstance(relative, str):
                inspect_pdf(root, relative, page_count, width_mm, height_mm, errors, warnings)

    inspect_separate_profile(root, data, pages, errors, warnings)
    qa = data.get("qa") or {}
    # This checks declared review evidence, not linguistic quality.
    add_path_check(root, data.get("language_review"), "language_review", errors)
    for key in ("story_reviewed", "language_reviewed", "visual_continuity_reviewed", "pdf_rendered_reviewed"):
        if qa.get(key) is not True:
            errors.append(f"qa.{key} must be true before final delivery")
    if qa.get("print_tested") is not True:
        if data.get("print_status") == "pending-physical-proof":
            warnings.append("qa.print_tested=false: digital package only; physical proof pending")
        else:
            errors.append("qa.print_tested is false; explicitly declare pending-physical-proof")

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Project directory containing book.json")
    args = parser.parse_args()
    root = args.project.expanduser().resolve()
    errors, warnings = validate(root)

    for item in warnings:
        print(f"WARNING: {item}")
    for item in errors:
        print(f"ERROR: {item}")
    if errors:
        print(f"FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"PASS: 0 errors, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

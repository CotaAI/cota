#!/usr/bin/env python3
"""Smoke tests for validate_book_package.py."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile

from pypdf import PdfWriter


HERE = Path(__file__).resolve().parent
VALIDATOR = HERE / "validate_book_package.py"


def write_pdf(path, pages=4, width_mm=210, height_mm=148):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=width_mm * 72 / 25.4, height=height_mm * 72 / 25.4)
    with path.open("wb") as stream:
        writer.write(stream)


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "previews").mkdir()
        (root / "illustrations").mkdir()
        for name in ("cover.jpg", "context.jpg", "detail.jpg", "ending.jpg", "back.jpg"):
            (root / "illustrations" / name).write_bytes(b"fixture")
        (root / "previews" / "full.jpg").write_bytes(b"fixture")
        (root / "previews" / "cover-back.png").write_bytes(b"fixture")
        (root / "打印说明.md").write_text("A5横版，实际大小100%。", encoding="utf-8")
        (root / "语言审校.md").write_text("测试夹具的审校记录，不是实际绘本。", encoding="utf-8")
        write_pdf(root / "reading.pdf")
        write_pdf(root / "home.pdf")

        manifest = {
            "title": "测试绘本",
            "audience_age": "3-5岁",
            "book_type": "behavior-story",
            "language": "zh-CN",
            "page_count": 4,
            "format": {
                "paper": "A5",
                "width_mm": 210,
                "height_mm": 148,
                "orientation": "landscape",
                "requires_trimming": False,
            },
            "binding": "saddle-stitch",
            "printing": {"home": True, "professional": False},
            "pages": [
                {"page": 1, "role": "cover", "layout": "cover", "asset": "illustrations/cover.jpg"},
                {
                    "page": 2,
                    "role": "story",
                    "layout": "context-to-detail",
                    "arrow_count": 1,
                    "context_asset": "illustrations/context.jpg",
                    "detail_asset": "illustrations/detail.jpg",
                },
                {"page": 3, "role": "ending", "layout": "quiet-page", "asset": "illustrations/ending.jpg"},
                {"page": 4, "role": "back-cover", "layout": "back", "asset": "illustrations/back.jpg"},
            ],
            "deliverables": {
                "reading_pdf": "reading.pdf",
                "home_print_pdf": "home.pdf",
                "professional_print_pdf": "",
                "printing_instructions": "打印说明.md",
                "full_preview": "previews/full.jpg",
                "cover_back_preview": "previews/cover-back.png",
            },
            "qa": {
                "story_reviewed": True,
                "language_reviewed": True,
                "visual_continuity_reviewed": True,
                "pdf_rendered_reviewed": True,
                "print_tested": True,
            },
            "language_review": "语言审校.md",
        }
        (root / "book.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

        passed = subprocess.run([sys.executable, str(VALIDATOR), str(root)], capture_output=True, text=True)
        assert passed.returncode == 0, passed.stdout + passed.stderr
        assert "PASS" in passed.stdout

        manifest["pages"][1]["arrow_count"] = 2
        (root / "book.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        failed = subprocess.run([sys.executable, str(VALIDATOR), str(root)], capture_output=True, text=True)
        assert failed.returncode == 1
        assert "arrow_count=1" in failed.stdout

    print("validator smoke tests passed")


if __name__ == "__main__":
    main()

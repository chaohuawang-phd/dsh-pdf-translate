# SPDX-License-Identifier: AGPL-3.0-only
"""Create a synthetic document for local translation tests and dsh smoke runs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf as pdf


TRANSLATIONS = {
    "en": [
        ("Context-aware document translation", "结合上下文的文档翻译"),
        (
            "A cache stores reusable results across requests.\n"
            "It reduces repeated work while the source stays unchanged.",
            "缓存保存可供后续请求复用的结果。\n原文保持不变时，缓存可以减少重复工作。",
        ),
    ],
    "zh": [
        ("结合全文上下文的文档翻译", "Context-aware translation"),
        (
            "缓存会保存可重复使用的结果，供后续请求调用。\n"
            "当原文保持不变时，它可以减少多次请求中的重复工作。",
            "A cache stores reusable results across requests.\n"
            "It reduces repeated work while the source stays unchanged.",
        ),
    ],
    "ja": [
        ("全文の文脈を考慮した文書翻訳", "结合全文上下文的文档翻译"),
        (
            "キャッシュは後のリクエストで再利用できる結果を保存します。\n"
            "原文が変わらない間、それによって繰り返しの処理を減らせます。",
            "缓存保存可供后续请求复用的结果。\n原文保持不变时，缓存可以减少重复工作。",
        ),
    ],
}


def write_font(destination: Path) -> Path:
    """Use the CJK font included in the installed PyMuPDF runtime."""
    destination.write_bytes(pdf.Font("cjk").buffer)
    return destination


def illustration_png() -> bytes:
    with pdf.open() as document:
        page = document.new_page(width=200, height=65)
        page.draw_rect((0, 0, 200, 65), fill=(0.90, 0.95, 1), color=(0.2, 0.3, 0.5))
        page.draw_circle((30, 32), 15, color=(0.2, 0.3, 0.5), fill=(0.5, 0.7, 0.9))
        page.insert_text((60, 36), "Cache -> Result", fontsize=12)
        return page.get_pixmap(alpha=False).tobytes("png")


def create_document(destination: Path, font: Path, language="en", scanned_page=False):
    """Return expected translations and protected regions for generated content."""
    rows = TRANSLATIONS[language]
    protected = pdf.Rect(45, 230, 550, 755)
    with pdf.open() as document:
        page = document.new_page(width=595, height=842)
        for box, text, size in [
            ((50, 50, 550, 100), rows[0][0], 17),
            ((50, 120, 550, 205), rows[1][0], 12),
        ]:
            remaining = page.insert_textbox(box, text, fontsize=size, fontname="FixtureFont", fontfile=str(font))
            if remaining < 0:
                raise ValueError("Synthetic fixture text did not fit")

        page.insert_text((50, 250), "Table 1. Reused results", fontsize=11)
        for y in (270, 295, 320):
            page.draw_line((50, y), (350, y))
        for x in (50, 210, 350):
            page.draw_line((x, 270), (x, 320))
        page.insert_text((60, 287), "Method", fontsize=10)
        page.insert_text((220, 287), "Count", fontsize=10)
        page.insert_text((60, 312), "Cache", fontsize=10)
        page.insert_text((220, 312), "7", fontsize=10)
        page.insert_text((50, 340), "Table note: counts remain unchanged.", fontsize=9)

        page.insert_image(pdf.Rect(50, 370, 250, 435), stream=illustration_png())
        page.insert_text((50, 455), "Figure 1. Cache and result", fontsize=11)

        page.insert_text((50, 510), "Code example", fontsize=11)
        page.insert_text((50, 535), "cache[key] = result  # keep this code", fontsize=10, fontname="cour")

        page.insert_text((50, 600), "References", fontsize=12)
        page.insert_text((50, 625), "[1] Example Author. Cache study. 2026.", fontsize=10)
        page.insert_text((50, 650), "https://example.org/cache", fontsize=10)
        link_rect = page.search_for("https://example.org/cache")[0]
        page.insert_link({"kind": pdf.LINK_URI, "from": link_rect, "uri": "https://example.org/cache"})

        if scanned_page:
            scan = document.new_page(width=595, height=842)
            scan.insert_image(scan.rect, stream=illustration_png(), keep_proportion=False)
        document.save(destination)
    return {"translations": rows, "protected": protected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".test-output/smoke-input.pdf"))
    parser.add_argument("--language", choices=tuple(TRANSLATIONS), default="en")
    parser.add_argument("--scanned-page", action="store_true")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        parser.error("The output already exists. Choose a new path.")
    font = args.output.parent / "fixture-cjk.ttf"
    write_font(font)
    create_document(args.output, font, args.language, args.scanned_page)
    print(json.dumps({"input": str(args.output.resolve()), "font": str(font.resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

# SPDX-License-Identifier: AGPL-3.0-only
"""Extract local PDF text, then typeset block translations supplied by the current chat."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata


def page_blocks(page):
    """Split interleaved columns / table cells when the next line returns up or sideways."""
    flags = pdf.TEXTFLAGS_DICT & ~pdf.TEXT_PRESERVE_IMAGES
    runs = []
    for block in page.get_text("dict", flags=flags)["blocks"]:
        run = []
        for line in block.get("lines", []):
            if not any(span["text"].strip() for span in line["spans"]):
                continue
            rect = pdf.Rect(line["bbox"])
            if run:
                previous = pdf.Rect(run[-1]["bbox"])
                sideways = rect.x0 > previous.x1 + 3 or rect.x1 < previous.x0 - 3
                if rect.y0 < previous.y0 - 3 or (sideways and rect.y0 < previous.y1 - 1):
                    run = []
            if not run:
                runs.append(run)
            run.append(line)
    return runs


def inspect_source(document, digest, target):
    from pdf_input_preflight import classify_page

    pages = []
    for page in document:
        number = page.number + 1
        blocks = []
        for i, run in enumerate(page_blocks(page), 1):
            box = pdf.Rect()
            lines = []
            for line in run:
                box |= pdf.Rect(line["bbox"])
                lines.append("".join(span["text"] for span in line["spans"]).strip())
            blocks.append({"id": f"p{number}-b{i}", "bbox": list(box), "text": "\n".join(lines)})
        pages.append({"number": number, "kind": classify_page(page)["kind"], "blocks": blocks})
    return {"schema_version": 1, "source_sha256": digest, "target_language": target, "pages": pages}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def decisions(plan, manifest):
    if not isinstance(plan, dict) or plan.get("source_sha256") != manifest["source_sha256"]:
        raise ValueError("Translation plan is missing the current source_sha256.")
    if plan.get("target_language", manifest["target_language"]) != manifest["target_language"]:
        raise ValueError("Translation plan and manifest have different target languages.")
    rows = plan.get("blocks")
    if not isinstance(rows, list):
        raise ValueError("Translation plan needs a blocks array.")
    expected = {b["id"] for p in manifest["pages"] for b in p["blocks"]}
    results = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each translation plan entry must be an object.")
        key, action = row.get("id"), row.get("action")
        if not isinstance(key, str) or key not in expected or key in results:
            raise ValueError(f"Unknown or repeated block ID: {key!r}")
        if action == "preserve" and not row.get("text"):
            results[key] = None
        elif action == "translate" and isinstance(row.get("text"), str) and row["text"].strip():
            results[key] = row["text"].strip()
        else:
            raise ValueError(f"{key}: choose preserve, or translate with nonempty plain text.")
    missing = expected.difference(results)
    if missing:
        raise ValueError("Missing translation decisions: " + ", ".join(sorted(missing)[:12]))
    if not any(results.values()):
        raise ValueError("All blocks were preserved. No translated PDF was produced.")
    return results


def compact(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).replace("\u00ad", ""))


def capture_links(page, changed):
    links = []
    for link in page.get_links():
        rect = link["from"]
        blocks = [b for b in changed if rect.intersects(pdf.Rect(b["bbox"]))]
        # Preserve the actual GoTo / URI destination (including a named destination),
        # not a guessed target page. The source objects stay in this same PDF.
        actions = {}
        for key in ("A", "Dest"):
            kind, value = page.parent.xref_get_key(link["xref"], key)
            if kind != "null":
                actions[key] = pdf.get_pdf_str(value) if kind == "string" else value
        links.append((link, blocks, actions))
        if blocks:
            page.delete_link(link)
    return links


def rebind_links(page, links, choices):
    if not links:
        return
    current = {link["xref"] for link in page.get_links()}
    unresolved = []
    restored = set()
    for original, blocks, actions in links:
        rect = original["from"]
        if not blocks and original["xref"] in current:
            continue
        if blocks:
            label = ", ".join(b["id"] for b in blocks)
            # Source captions and reference numbers can change their meaning or
            # position. Only relocate a literal, unique URI/email in its own block.
            uri = original.get("uri", "")
            needle = uri.removeprefix("mailto:")
            if len(blocks) != 1 or not needle or choices[blocks[0]["id"]].count(needle) != 1:
                unresolved.append(label)
                continue
            hits = page.search_for(needle, clip=pdf.Rect(blocks[0]["bbox"]))
            if len(hits) != 1:
                unresolved.append(label)
                continue
            rect = hits[0]
        if not actions:
            unresolved.append(", ".join(b["id"] for b in blocks) or "unchanged region")
            continue
        identity = (tuple(rect), tuple(actions.items()))
        if identity in restored:
            continue
        page.insert_link({"kind": pdf.LINK_GOTO, "from": rect, "page": page.number})
        xref = page.annot_xrefs()[-1][0]
        for key in ("A", "Dest"):
            page.parent.xref_set_key(xref, key, actions.get(key, "null"))
        restored.add(identity)
    if unresolved:
        print(f"Page {page.number + 1}: {len(unresolved)} original link region(s) need manual "
              f"alignment in {', '.join(dict.fromkeys(unresolved))}.", file=sys.stderr)


def write_page(page, page_info, choices, font_css, archive):
    blocks = page_info["blocks"]
    changed = [b for b in blocks if choices[b["id"]] is not None]
    if not changed:
        return
    if page_info["kind"] in {"scanned_image", "no_text_layer"}:
        raise ValueError(f"Page {page_info['number']} has no reliable native text layer. Preserve this page.")
    if any(a.type[0] == pdf.PDF_ANNOT_REDACT for a in page.annots() or []):
        raise ValueError(f"Page {page_info['number']} contains pending redactions. Use a reviewed copy.")
    # Rounded coordinate intersection at a line's edge is normal. Overlapping interiors
    # usually indicate nested labels, mixed equations or a table unsuited to block replacement.
    images = [pdf.Rect(item["bbox"]) for item in page.get_image_info()]
    runs = page_blocks(page)
    work = []
    for block, lines in zip(blocks, runs):
        key = block["id"]
        translation = choices[key]
        if translation is None:
            continue
        box = pdf.Rect(block["bbox"])
        if any(abs(line["dir"][0] - 1) > .01 or abs(line["dir"][1]) > .01 for line in lines):
            raise ValueError(f"{key}: rotated text needs custom layout or an explicit preserve decision.")
        inner = box + (0.6, 1, -0.6, -1)
        if inner.is_empty or not page.rect.contains(box * page.rotation_matrix):
            raise ValueError(f"{key}: irregular block bounds. Use custom layout or preserve this block.")
        if any(inner.intersects(image) for image in images):
            raise ValueError(f"{key}: block overlaps an image. Inspect it and use custom layout or preserve it.")
        for other in blocks:
            if other["id"] == key:
                continue
            overlap = inner & pdf.Rect(other["bbox"])
            if not overlap.is_empty and overlap.width > 1 and overlap.height > 1.5:
                raise ValueError(f"{key}: overlapping block {other['id']}. Use custom layout or preserve the region.")
        spans = [s for line in lines for s in line["spans"] if s["text"].strip()]
        style = max(spans, key=lambda s: len(s["text"].strip()))
        for span in spans:
            # A thin stripe erases the selected glyphs without touching adjacent line boxes.
            rect = pdf.Rect(span["bbox"])
            middle = (rect.y0 + rect.y1) / 2
            stripe = pdf.Rect(rect.x0 + .02, middle - .10, rect.x1 - .02, middle + .10)
            if not stripe.is_empty:
                page.add_redact_annot(stripe, fill=False, cross_out=False)
        work.append((key, box, translation, style))
    links = capture_links(page, changed)
    page.apply_redactions(images=0, graphics=0, text=0)
    for key, box, translation, style in work:
        size = style["size"]
        weight = "bold" if style["flags"] & 16 else "normal"
        css = (font_css + f"body{{margin:0;padding:0;font-size:{size}pt;line-height:1.06;"
               f"font-weight:{weight};color:#{style['color'] & 0xffffff:06x};}}")
        markup = html.escape(translation).replace("\n", "<br>")
        spare, _ = page.insert_htmlbox(box, markup, css=css, archive=archive, scale_low=.75)
        if spare < 0:
            raise ValueError(f"{key}: translation overflows its source block. Revise its wording or use custom layout.")
    # Verify the final searchable text, including unmodified blocks. A problem must be
    # reported before publishing the document, even when the renderer reports a fit.
    output_text = compact(page.get_text())
    for block in blocks:
        actual = choices[block["id"]]
        expected = block["text"] if actual is None else actual
        if compact(expected) not in output_text:
            raise ValueError(f"{block['id']}: text did not round-trip. Inspect this page or choose a suitable --font.")
    rebind_links(page, links, choices)


def save_new(destination, writer):
    """Publish a complete file without overwriting a previous or concurrent result."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError(f"Choose a new output path: {destination}")
    with tempfile.TemporaryDirectory(prefix=".pdf-session-", dir=destination.parent) as staging:
        complete = Path(staging) / destination.name
        writer(complete)
        try:
            os.link(complete, destination)
        except FileExistsError:
            raise ValueError(f"Another file already exists: {destination}") from None
        except OSError:
            # Filesystems without hard links: reserve the name exclusively before copying.
            import shutil
            with complete.open("rb") as src, destination.open("xb") as dst:
                try:
                    shutil.copyfileobj(src, dst)
                    dst.flush()
                except BaseException:
                    dst.close()
                    destination.unlink()
                    raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="write a private source manifest for the current chat")
    render = commands.add_parser("render", help="produce a single translated PDF from the chat's decisions")
    for command in (extract, render):
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--manifest", type=Path, required=True)
    extract.add_argument("--target-language", choices=("zh", "en"), default="zh")
    render.add_argument("--translations", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--font", type=Path, help="local font file to embed")
    args = parser.parse_args(argv)
    global pdf
    import pymupdf as pdf

    source = args.input.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    with pdf.open(stream=source, filetype="pdf") as document:
        if document.needs_pass or not len(document):
            raise ValueError("Provide a readable, unlocked PDF with at least one page.")
        if args.command == "extract":
            info = inspect_source(document, digest, args.target_language)
            save_new(args.manifest, lambda p: p.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"))
            return
        if args.output.suffix.lower() != ".pdf":
            raise ValueError("--output must be a new .pdf file.")
        info = load_json(args.manifest)
        if not isinstance(info, dict) or info.get("target_language") not in ("zh", "en"):
            raise ValueError("Invalid session manifest. Extract the source again.")
        if info != inspect_source(document, digest, info["target_language"]):
            raise ValueError("Manifest or source changed. Extract and review the source again.")
        choices = decisions(load_json(args.translations), info)
        css, archive = "", None
        if args.font:
            archive = pdf.Archive((args.font.read_bytes(), "localfont"))
            css = '@font-face{font-family:SessionFont;src:url(localfont);}body{font-family:SessionFont;}'
        for page, page_info in zip(document, info["pages"]):
            write_page(page, page_info, choices, css, archive)
        def save_pdf(path):
            document.subset_fonts()
            document.save(path, garbage=4, deflate=True)
            with pdf.open(path) as check:
                if len(check) != len(document):
                    raise ValueError("Output page count changed.")
        save_new(args.output, save_pdf)


if __name__ == "__main__":
    try:
        main()
    except (ImportError, ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        sys.exit(str(exc))

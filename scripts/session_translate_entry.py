# SPDX-License-Identifier: AGPL-3.0-only
"""Prepare text for the current chat or publish its completed translations locally."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile


def private_manifest(source_hash, language):
    user_id = str(os.getuid()) if hasattr(os, "getuid") else "user"
    private = Path(tempfile.gettempdir()) / ("dsh-session-pdf-" + user_id)
    private.mkdir(mode=0o700, exist_ok=True)
    meta = private.lstat()
    if not stat.S_ISDIR(meta.st_mode) or getattr(meta, "st_file_attributes", 0) & 0x400:
        raise ValueError("The private translation cache must be a regular directory.")
    if hasattr(os, "getuid") and (meta.st_uid != os.getuid() or meta.st_mode & 0o077):
        raise ValueError("The translation cache must be accessible only to the current user.")
    helper_version = hashlib.sha256(Path(__file__).with_name("session_pdf.py").read_bytes()).hexdigest()[:12]
    return private / f"{source_hash}-{language}-{helper_version}.json"


def translate(args):
    from session_pdf import main as pdf_main

    source = args.input.resolve()
    with source.open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    source_hash = digest.hexdigest()
    manifest = args.manifest.absolute() if args.manifest else private_manifest(source_hash, args.target_language)
    output_dir = args.output.resolve()
    output_pdf = output_dir / "译文.pdf"
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError("--output must be a directory.")
    if args.manifest and manifest.resolve().is_relative_to(output_dir) and not manifest.exists():
        raise ValueError("Place the private source manifest outside the PDF delivery directory.")
    if args.font and not args.font.is_file():
        raise ValueError("--font must point to a readable local font file.")
    different_files = [source, manifest.resolve(), output_pdf.resolve()]
    if args.translations:
        different_files.append(args.translations.resolve())
    if len(set(different_files)) != len(different_files):
        raise ValueError("Input, private manifest, translations and output must have different paths.")
    if output_pdf.exists():
        raise ValueError("译文.pdf already exists. Choose a new output directory.")
    if manifest.is_symlink():
        raise ValueError("The private manifest must be a regular file.")
    if not manifest.exists():
        try:
            pdf_main(["extract", "--input", str(source), "--manifest", str(manifest),
                      "--target-language", args.target_language])
        except (FileExistsError, ValueError):
            # A concurrent extraction can publish the same manifest first.
            if not manifest.is_file():
                raise
    with manifest.open(encoding="utf-8-sig") as stream:
        info = json.load(stream)
    if (not isinstance(info, dict) or info.get("schema_version") != 1
            or info.get("source_sha256") != source_hash or info.get("target_language") != args.target_language):
        raise ValueError("The manifest does not match the input PDF and target language.")
    font_args = ["--font", str(args.font.resolve())] if args.font else []
    if args.translations:
        pdf_main(["render", "--input", str(source), "--manifest", str(manifest),
                  "--translations", str(args.translations.resolve()), "--output", str(output_pdf), *font_args])
        return {"status": "completed", "output_pdf": str(output_pdf)}

    # Inputs may share a source manifest; each conversation owns its draft.
    draft_dir = Path(tempfile.mkdtemp(prefix="dsh-pdf-draft-"))
    translations = draft_dir / "translations.json"
    return {
        "status": "awaiting_current_chat_translation",
        "manifest": str(manifest),
        "instructions": (
            "由当前对话沿用窗口的模型和思考设置，先阅读 SKILL.md 与 references/academic-translation-policy.md。"
            "先通读完整原文，建立全文上下文、术语表和指代关系，再按语义段落翻译并映射回块 ID。"
            "表格、图片及其标题说明、完整参考文献区、代码和算法原样保留，对完整保护块使用 preserve。"
            "混合块按学术翻译规则精确分区写回。全篇译文采用统一且覆盖所需字形的字体，"
            "保留源文版式和字号层级，保护区域沿用原始字体。将决定写入下方 JSON 路径，"
            "向 render_argv 传入选定的 --font，再运行并核对全文语义、字体和保护区域。"
        ),
        "translations": str(translations),
        "plan_schema": {"source_sha256": source_hash, "target_language": args.target_language,
                        "blocks": [{"id": "<manifest block id>", "action": "translate", "text": "<translation>"}]},
        "preserve_block": {"id": "<protected block id>", "action": "preserve"},
        "render_argv": [sys.executable, str(Path(__file__).with_name("paper_translation_workflow.py")), "translate",
                        "--input", str(source), "--output", str(output_dir), "--target-language", args.target_language,
                        "--manifest", str(manifest), "--translations", str(translations), *font_args],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="paper_translation_workflow.py translate", description=__doc__,
                                     allow_abbrev=False)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="directory for 译文.pdf")
    parser.add_argument("--target-language", choices=("zh", "en"), default="zh")
    parser.add_argument("--manifest", type=Path, help="private source manifest (default: user temporary directory)")
    parser.add_argument("--translations", type=Path, help="render completed current-chat decisions")
    parser.add_argument("--font", type=Path, help="local font file shared by all translated blocks")
    parser.add_argument("--resume", action="store_true", help="reuse a matching source manifest (also the default)")
    args, extra = parser.parse_known_args(argv)
    if extra:
        parser.error("unsupported arguments for the current-chat translation route")
    try:
        result = translate(args)
    except (OSError, ValueError, RuntimeError, ImportError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

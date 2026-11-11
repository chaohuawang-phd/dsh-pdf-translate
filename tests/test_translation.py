# SPDX-License-Identifier: AGPL-3.0-only
"""Exercise the shipped command with generated PDFs and translation decisions."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import pymupdf as pdf

from create_smoke_pdf import create_document, write_font


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts" / "paper_translation_workflow.py"


def compact(text):
    return "".join(text.split())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dsh-pdf-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.source = self.directory / "source.pdf"
        self.manifest = self.directory / "manifest.json"
        self.plan_path = self.directory / "translations.json"
        self.output = self.directory / "delivery"
        self.font = write_font(self.directory / "fixture.ttf")
        self.target_language = "zh"

    def invoke(self, *extra):
        result = subprocess.run(
            [sys.executable, str(ENTRY), "translate", "--input", str(self.source),
             "--output", str(self.output), "--target-language", self.target_language,
             "--manifest", str(self.manifest), *map(str, extra)],
            capture_output=True, text=True, timeout=45,
        )
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            self.fail(f"Command returned non-JSON output ({result.returncode}): {result.stdout}\n{result.stderr}")
        return result, payload

    def prepare(self, language="en", scanned_page=False):
        self.target_language = "en" if language == "zh" else "zh"
        self.fixture = create_document(self.source, self.font, language, scanned_page)
        self.original_hash = digest(self.source)
        result, payload = self.invoke()
        self.assertEqual(result.returncode, 0, payload)
        self.assertEqual(payload["status"], "awaiting_current_chat_translation")
        self.assertFalse(self.output.exists())
        self.addCleanup(shutil.rmtree, Path(payload["translations"]).parent, True)
        self.info = json.loads(self.manifest.read_text())
        self.plan = {
            "source_sha256": self.info["source_sha256"],
            "target_language": self.target_language,
            "blocks": [],
        }
        mapping = {compact(source): translated for source, translated in self.fixture["translations"]}
        for page in self.info["pages"]:
            for block in page["blocks"]:
                translated = mapping.get(compact(block["text"]))
                row = {"id": block["id"], "action": "preserve"}
                if translated is not None:
                    row.update(action="translate", text=translated)
                self.plan["blocks"].append(row)
        self.assertEqual(sum(row["action"] == "translate" for row in self.plan["blocks"]), 2)
        return payload

    def render(self, plan=None, *extra):
        self.plan_path.write_text(json.dumps(self.plan if plan is None else plan, ensure_ascii=False))
        return self.invoke("--translations", self.plan_path, "--font", self.font, *extra)

    def assert_translation(self, result, payload):
        self.assertEqual(result.returncode, 0, payload)
        self.assertEqual(payload["status"], "completed")
        output = self.output / "译文.pdf"
        self.assertEqual(Path(payload["output_pdf"]), output)
        self.assertEqual(list(self.output.iterdir()), [output])
        self.assertEqual(digest(self.source), self.original_hash)
        with pdf.open(self.source) as source, pdf.open(output) as translated:
            self.assertEqual(len(source), len(translated))
            self.assertEqual(source[0].rect, translated[0].rect)
            text = compact(translated[0].get_text())
            for original, expected in self.fixture["translations"]:
                self.assertIn(compact(expected), text)
                self.assertNotIn(compact(original), text)
            clip = self.fixture["protected"]
            self.assertEqual(source[0].get_text(clip=clip), translated[0].get_text(clip=clip))
            for zoom in (1, 2):
                self.assertEqual(
                    source[0].get_pixmap(matrix=pdf.Matrix(zoom, zoom), clip=clip, alpha=False).samples,
                    translated[0].get_pixmap(matrix=pdf.Matrix(zoom, zoom), clip=clip, alpha=False).samples,
                    "Protected table, image, caption, code and references changed",
                )
            self.assertEqual(
                [(link["uri"], tuple(link["from"])) for link in source[0].get_links()],
                [(link["uri"], tuple(link["from"])) for link in translated[0].get_links()],
            )
        return output

    def test_english_to_chinese(self):
        self.prepare("en")
        self.assert_translation(*self.render())

    def test_chinese_to_english(self):
        self.prepare("zh")
        self.assert_translation(*self.render())

    def test_japanese_to_chinese(self):
        self.prepare("ja")
        self.assert_translation(*self.render())

    def test_default_cache_and_emitted_command(self):
        self.prepare()
        environment = os.environ.copy()
        environment["TMPDIR"] = str(self.directory)
        result = subprocess.run(
            [sys.executable, str(ENTRY), "translate", "--input", str(self.source),
             "--output", str(self.output), "--target-language", self.target_language],
            capture_output=True, text=True, timeout=45, cwd=self.directory, env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(Path(payload["manifest"]).is_relative_to(self.directory))
        self.assertNotEqual(Path(payload["manifest"]), self.manifest)
        self.assertFalse(Path(payload["manifest"]).is_relative_to(self.output))
        Path(payload["translations"]).write_text(json.dumps(self.plan, ensure_ascii=False))
        rendered = subprocess.run(
            [*payload["render_argv"], "--font", str(self.font)],
            capture_output=True, text=True, timeout=45, cwd=self.directory, env=environment,
        )
        self.assert_translation(rendered, json.loads(rendered.stdout))

    def test_scanned_page_preserved(self):
        self.prepare(scanned_page=True)
        self.assertEqual(self.info["pages"][1]["kind"], "scanned_image")
        output = self.assert_translation(*self.render())
        with pdf.open(self.source) as source, pdf.open(output) as translated:
            self.assertEqual(source[1].get_pixmap().samples, translated[1].get_pixmap().samples)

    def test_plan_validation(self):
        self.prepare()
        invalid_plans = []
        plan = copy.deepcopy(self.plan)
        plan["source_sha256"] = "0" * 64
        invalid_plans.append(("source hash", plan, "source_sha256"))
        plan = copy.deepcopy(self.plan)
        plan["target_language"] = "en"
        invalid_plans.append(("language", plan, "different target languages"))
        plan = copy.deepcopy(self.plan)
        plan["blocks"].pop()
        invalid_plans.append(("missing", plan, "Missing translation decisions"))
        plan = copy.deepcopy(self.plan)
        plan["blocks"].append(copy.deepcopy(plan["blocks"][0]))
        invalid_plans.append(("duplicate", plan, "Unknown or repeated"))
        plan = copy.deepcopy(self.plan)
        plan["blocks"][0]["id"] = "p999-b999"
        invalid_plans.append(("unknown", plan, "Unknown or repeated"))
        plan = copy.deepcopy(self.plan)
        plan["blocks"][0]["text"] = " "
        invalid_plans.append(("empty translation", plan, "nonempty plain text"))
        plan = copy.deepcopy(self.plan)
        plan["blocks"] = [{"id": row["id"], "action": "preserve"} for row in plan["blocks"]]
        invalid_plans.append(("all preserved", plan, "All blocks were preserved"))
        invalid_plans.append(("wrong top level", [], "source_sha256"))
        for name, plan, expected_error in invalid_plans:
            with self.subTest(name=name):
                result, payload = self.render(plan)
                self.assertEqual(result.returncode, 2, payload)
                self.assertEqual(payload["status"], "blocked")
                self.assertIn(expected_error, payload["error"])
                self.assertFalse((self.output / "译文.pdf").exists())
                self.assertEqual(digest(self.source), self.original_hash)

    def test_modified_manifest_rejected(self):
        self.prepare()
        self.info["pages"][0]["blocks"][0]["bbox"][0] += 5
        self.manifest.write_text(json.dumps(self.info))
        result, payload = self.render()
        self.assertEqual(result.returncode, 2)
        self.assertIn("Manifest or source changed", payload["error"])
        self.assertFalse((self.output / "译文.pdf").exists())

    def test_modified_source_rejected(self):
        self.prepare()
        with self.source.open("ab") as stream:
            stream.write(b"\n% Source changed\n")
        result, payload = self.render()
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not match", payload["error"])
        self.assertFalse((self.output / "译文.pdf").exists())

    def test_existing_output_kept(self):
        self.prepare()
        output = self.assert_translation(*self.render())
        previous_hash = digest(output)
        result, payload = self.render()
        self.assertEqual(result.returncode, 2)
        self.assertIn("already exists", payload["error"])
        self.assertEqual(digest(output), previous_hash)

    def test_concurrent_output_collision(self):
        self.prepare()
        self.plan_path.write_text(json.dumps(self.plan, ensure_ascii=False))
        def render_same_destination():
            return self.invoke("--translations", self.plan_path, "--font", self.font)
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = list(pool.map(lambda _: render_same_destination(), range(2)))
        self.assertEqual(sorted(result.returncode for result, _ in attempts), [0, 2])
        completed = next(attempt for attempt in attempts if attempt[0].returncode == 0)
        self.assert_translation(*completed)

    def test_invalid_font_rejected(self):
        self.prepare()
        self.plan_path.write_text(json.dumps(self.plan))
        result, payload = self.invoke("--translations", self.plan_path, "--font", self.directory / "missing.ttf")
        self.assertEqual(result.returncode, 2)
        self.assertIn("readable local font", payload["error"])
        self.assertFalse((self.output / "译文.pdf").exists())

    def test_missing_input_rejected(self):
        result, payload = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "blocked")

    def test_corrupt_input_rejected(self):
        self.source.write_bytes(b"This is not a PDF.")
        result, payload = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(self.manifest.exists())

    def test_manifest_in_delivery_rejected(self):
        create_document(self.source, self.font)
        self.manifest = self.output / "manifest.json"
        result, payload = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside the PDF delivery directory", payload["error"])

    def test_resume_reuses_manifest(self):
        self.prepare()
        previous = self.manifest.read_bytes()
        result, payload = self.invoke("--resume")
        self.addCleanup(shutil.rmtree, Path(payload["translations"]).parent, True)
        self.assertEqual(result.returncode, 0, payload)
        self.assertEqual(self.manifest.read_bytes(), previous)
        self.assert_translation(*self.render())


if __name__ == "__main__":
    unittest.main()

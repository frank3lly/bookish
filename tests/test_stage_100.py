import os
import shutil
import tempfile
import unittest
from unittest import mock

import curses
from google.genai import types

from bookish_pkg.config import DEFAULT_GEMINI_MODEL, ATTACHMENTS_MEDIA_DIR
from bookish_pkg.generator import curses_prompt_assignment, generate_assignment_draft, DEFAULT_SYSTEM_INSTRUCTION
from bookish_pkg.pipeline import create_handoff_file
from bookish_pkg.scraper import extract_docx_images, extract_pdf_images
from bookish_pkg.utils import open_draft_in_editor


class TestStage100(unittest.TestCase):

    def test_default_gemini_model(self):
        """Validar que el modelo por defecto resuelto sea gemini-2.5-pro."""
        self.assertEqual(DEFAULT_GEMINI_MODEL, "gemini-2.5-pro")

    def test_docx_image_extraction(self):
        """Validar extracción de imágenes desde archivo docx existente."""
        docx_path = "data/attachments/ing031guía3b.docx"
        if not os.path.exists(docx_path):
            self.skipTest(f"{docx_path} not found")

        with tempfile.TemporaryDirectory() as temp_dir:
            extracted = extract_docx_images(docx_path, temp_dir)
            self.assertEqual(len(extracted), 6)
            for img in extracted:
                self.assertTrue(os.path.exists(img))
                self.assertTrue(os.path.isabs(img))

    def test_no_option_m_in_ui_and_jk_navigation(self):
        """Validar que la opción [M] no exista en la interfaz y que J/K naveguen."""
        with mock.patch("curses.curs_set"), \
             mock.patch("curses.start_color"), \
             mock.patch("curses.use_default_colors"), \
             mock.patch("curses.init_pair"), \
             mock.patch("curses.color_pair", return_value=0):

            stdscr = mock.MagicMock()
            stdscr.getmaxyx.return_value = (24, 80)
            item = {"title": "Test Title", "description": "Short Description"}

            # Test navigation with 'k' -> 'prev'
            stdscr.getch.return_value = ord("k")
            action, _ = curses_prompt_assignment(stdscr, item, 1, 1)
            self.assertEqual(action, "prev")

            # Test navigation with 'j' -> 'next'
            stdscr.getch.return_value = ord("j")
            action, _ = curses_prompt_assignment(stdscr, item, 1, 1)
            self.assertEqual(action, "next")

            # Test that 'm' is ignored and does not return 'markdown_only'
            stdscr.getch.side_effect = [ord("m"), ord("q")]
            action, _ = curses_prompt_assignment(stdscr, item, 1, 1)
            self.assertEqual(action, "quit")

    def test_open_draft_in_editor_exit_codes(self):
        """Validar apertura interactiva en editor con códigos 0 y distinto de cero."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"# Test Draft")
            tmp_path = f.name

        try:
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0)
                self.assertTrue(open_draft_in_editor(tmp_path))

            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=1)
                self.assertFalse(open_draft_in_editor(tmp_path))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_multimodal_gemini_payload_and_system_instruction(self):
        """Validar construcción multimodal y mención de esquemas en instrucción."""
        self.assertIn("ANÁLISIS MULTIMODAL DE ESQUEMAS Y CIRCUITOS", DEFAULT_SYSTEM_INSTRUCTION)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_f:
            img_f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
            img_path = img_f.name

        try:
            mock_client = mock.MagicMock()
            mock_response = mock.MagicMock()
            mock_response.text = "Generated Answer"
            mock_client.models.generate_content.return_value = mock_response

            res = generate_assignment_draft(
                mock_client,
                title="Amplificador Operacional",
                description="Resuelva circuito",
                course_code="ING-031",
                course_name="Fundamentos",
                due_date="2026-11-20",
                image_paths=[img_path]
            )
            self.assertEqual(res, "Generated Answer")

            call_kwargs = mock_client.models.generate_content.call_args[1]
            contents = call_kwargs["contents"]
            self.assertEqual(len(contents), 2)
            self.assertIsInstance(contents[1], types.Part)
            self.assertEqual(call_kwargs["model"], "gemini-2.5-pro")
        finally:
            if os.path.exists(img_path):
                os.remove(img_path)

    def test_handoff_includes_attached_images(self):
        """Validar que el handoff incluya la sección de imágenes extraídas."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_f:
            img_f.write(b"\x89PNG")
            img_path = img_f.name

        try:
            item = {
                "title": "Prueba Handoff Esquemas",
                "course_code": "ING-031",
                "due_date": "2026-11-30",
                "description": "Circuito con diodos",
                "attached_images": [img_path]
            }
            h_path, out_draft = create_handoff_file(item)
            self.assertTrue(os.path.exists(h_path))
            with open(h_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("## Esquemas y Diagramas Extraídos", content)
            self.assertIn(img_path, content)
        finally:
            if os.path.exists(img_path):
                os.remove(img_path)


if __name__ == "__main__":
    unittest.main()

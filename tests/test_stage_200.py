import os
import tempfile
import unittest
from unittest import mock

from bookish_pkg.converter import HTML_TEMPLATE, preprocess_markdown, convert_md_to_pdf
from bookish_pkg.docs import get_converter_cheatsheet, generate_nvim_docs_script
from bookish_pkg.utils import normalize_image_path, open_draft_in_editor


class TestStage200(unittest.TestCase):

    def test_css_utility_classes_in_template(self):
        """Verificar presencia de todas las nuevas clases CSS en HTML_TEMPLATE."""
        expected_classes = [
            ".center", ".img-center", ".left", ".right",
            ".w-25", ".w-50", ".w-75", ".w-100",
            ".small", ".medium", ".large",
            "figure", "figcaption",
            ".image-grid-2", ".image-row",
            ".page-break-before", ".page-break-after"
        ]
        for cls in expected_classes:
            self.assertIn(cls, HTML_TEMPLATE, f"Falta la regla CSS '{cls}' en HTML_TEMPLATE")

    def test_windows_path_normalization(self):
        """Verificar normalización de rutas de Windows hacia /mnt/ en entorno Linux."""
        win_path_1 = r"C:\Users\frank\Pictures\circuito.png"
        self.assertEqual(normalize_image_path(win_path_1), "/mnt/c/Users/frank/Pictures/circuito.png")

        win_path_2 = 'D:/Documentos/grafico.jpg'
        self.assertEqual(normalize_image_path(win_path_2), "/mnt/d/Documentos/grafico.jpg")

        quoted_path = '"/home/user/img.png"'
        self.assertEqual(normalize_image_path(quoted_path), "/home/user/img.png")

    def test_extended_markdown_image_parsing(self):
        """Verificar parsing de sintaxis extendida ![Texto|clases](ruta)."""
        md_input = "![Esquema AMPOP|center|w-50|screenshot](esquema.png)"
        processed = preprocess_markdown(md_input)

        self.assertIn('<figure class="center w-50 screenshot">', processed)
        self.assertIn('<img src="esquema.png" class="center w-50 screenshot" alt="Esquema AMPOP" />', processed)
        self.assertIn('<figcaption>Esquema AMPOP</figcaption>', processed)

        # Sin clases (sintaxis estándar)
        md_standard = "![Foto Simple](foto.png)"
        processed_std = preprocess_markdown(md_standard)
        self.assertIn('<figure class="center">', processed_std)
        self.assertIn('<figcaption>Foto Simple</figcaption>', processed_std)

    def test_converter_cheatsheet(self):
        """Verificar generación y contenido del cheat sheet."""
        sheet = get_converter_cheatsheet()
        self.assertIn("CONVERTER FORMAT & CHEAT SHEET", sheet)
        self.assertIn("SINTAXIS RÁPIDA DE IMÁGENES EN MARKDOWN", sheet)
        self.assertIn("CLASES UTILITARIAS DISPONIBLES", sheet)
        self.assertIn("image-grid-2", sheet)
        self.assertIn("NORMALIZACIÓN DE RUTAS DE WINDOWS", sheet)

    def test_neovim_lua_script_generation(self):
        """Verificar estructura y sintaxis del script Lua para Neovim."""
        lua = generate_nvim_docs_script()
        self.assertIn("vim.api.nvim_create_buf", lua)
        self.assertIn("vim.api.nvim_open_win", lua)
        self.assertIn("border = \"rounded\"", lua)
        self.assertIn("BookishDocs", lua)
        self.assertIn("ConverterDocs", lua)
        self.assertIn("<F1>", lua)

    def test_open_draft_in_editor_passes_lua(self):
        """Verificar que open_draft_in_editor pasa el script Lua al invocar nvim."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf:
            tf.write(b"# Documento de Prueba")
            path = tf.name

        try:
            with mock.patch("shutil.which", return_value="/usr/bin/nvim"), \
                 mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0)
                result = open_draft_in_editor(path)
                self.assertTrue(result)
                cmd = mock_run.call_args[0][0]
                self.assertEqual(cmd[0], "nvim")
                self.assertEqual(cmd[1], "-c")
                self.assertTrue(cmd[2].startswith("luafile "))
                self.assertEqual(cmd[3], path)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_pdf_conversion_integration(self):
        """Verificar conversión a PDF con imágenes, tablas y clases utilitarias."""
        sample_md = """# Reporte Técnico de Prueba

Este es un párrafo justificativo con explicación técnica.

![Diagrama|center|w-50](logo.jpeg)

| Parámetro | Valor |
|---|---|
| Entrada | 5V |
| Salida | 12V |

<div class="page-break"></div>

## Sección Siguiente
Contenido en segunda página.
"""
        with tempfile.TemporaryDirectory() as td:
            md_file = os.path.join(td, "prueba_tecnica.md")
            pdf_file = os.path.join(td, "prueba_tecnica.pdf")
            with open(md_file, "w", encoding="utf-8") as f:
                f.write(sample_md)

            # Convert to PDF
            convert_md_to_pdf(target=md_file, output_dest=pdf_file)
            self.assertTrue(os.path.exists(pdf_file))
            self.assertGreater(os.path.getsize(pdf_file), 1000)


if __name__ == "__main__":
    unittest.main()

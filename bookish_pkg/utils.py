"""
Shared utility functions used across multiple Bookish modules.

Consolidates duplicated helpers (sanitize_filename, open_file_async,
cover page HTML builder, image inlining) into a single module.
"""

import os
import re
import logging
import shutil
import subprocess

from bookish_pkg.config import PROJECT_ROOT

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Filename sanitization (was duplicated in scraper, generator, converter)
# ---------------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    """
    Clean a string for safe use as a filename.
    Strips special characters, replaces whitespace with underscores, lowercases.
    """
    clean = re.sub(r'[^\w\s-]', '', name)
    clean = re.sub(r'[-\s]+', '_', clean)
    return clean.strip().lower()


# ---------------------------------------------------------------------------
# File opener (was in converter.py only)
# ---------------------------------------------------------------------------

def open_file_async(file_path: str) -> None:
    """
    Open a file with the system default viewer (non-blocking).
    Tries wslview -> xdg-open -> open in order.
    """
    for cmd in ("wslview", "xdg-open", "open"):
        if shutil.which(cmd):
            try:
                subprocess.Popen(
                    [cmd, file_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as e:
                log.debug("Could not launch %s for %s: %s", cmd, file_path, e)
            return
    log.debug("No file viewer found for %s", file_path)


# ---------------------------------------------------------------------------
# Cover page HTML builder (was duplicated in converter and pipeline)
# ---------------------------------------------------------------------------

def build_cover_page_html(
    course_code: str = "",
    title: str = "",
    student_name: str = "",
    student_enrolment: str = "",
    due_date: str = "",
) -> str:
    """
    Return the standard UCE cover-page HTML block used in drafts and presentations.
    """
    return (
        f'<div class="cover-page">\n'
        f'  <img src="logo.jpeg" alt="Universidad Central del Este" class="cover-logo" />\n'
        f'  <h2>Facultad de Ciencias e Ingenierías</h2>\n'
        f'  <h3>Escuela de Ingeniería de Software</h3>\n\n'
        f'  <p><strong>Asignatura:</strong> {course_code}</p>\n'
        f'  <p><strong>Asignación:</strong> {title}</p>\n'
        f'  <p><strong>Estudiante:</strong> {student_name}</p>\n'
        f'  <p><strong>Matrícula:</strong> {student_enrolment}</p>\n'
        f'  <p><strong>Fecha Límite:</strong> {due_date}</p>\n'
        f'</div>\n'
    )


# ---------------------------------------------------------------------------
# Image inlining for HTML (was in converter.py)
# ---------------------------------------------------------------------------

# Cache for base64-encoded images to avoid re-reading the same file
_image_cache: dict[str, str] = {}


def image_data_uri(src: str, base_dir: str | None = None) -> str:
    """
    Resolve an image path and return a base64 data URI.
    Checks: base_dir -> CWD -> data/images/ -> logo.jpeg special case.
    Results are cached in-memory to avoid redundant disk reads.
    """
    if not src or src.startswith(("data:", "http://", "https://")):
        return src

    # Build a cache key
    cache_key = f"{base_dir or ''}::{src}"
    if cache_key in _image_cache:
        return _image_cache[cache_key]

    resolved = None

    # Special case: logo.jpeg -> institutional logo
    if src == "logo.jpeg":
        resolved = os.path.join(PROJECT_ROOT, "data", "images", "Universidad_Central_del_Este.jpeg")
    else:
        # Candidate 1: relative to base_dir
        if base_dir:
            cand = os.path.abspath(os.path.join(base_dir, src))
            if os.path.exists(cand):
                resolved = cand
        # Candidate 2: direct / CWD-relative
        if not resolved and os.path.exists(src):
            resolved = os.path.abspath(src)
        # Candidate 3: data/images/
        if not resolved:
            cand = os.path.join(PROJECT_ROOT, "data", "images", src)
            if os.path.exists(cand):
                resolved = cand

    if not resolved or not os.path.exists(resolved):
        log.warning("Image not found: '%s'", src)
        return src

    import base64

    ext = os.path.splitext(resolved)[1].lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }
    mime = mime_map.get(ext, "image/png")

    try:
        with open(resolved, "rb") as img_file:
            b64_str = base64.b64encode(img_file.read()).decode("utf-8")
        uri = f"data:{mime};base64,{b64_str}"
        _image_cache[cache_key] = uri
        return uri
    except OSError as e:
        log.warning("Could not encode image '%s': %s", resolved, e)
        return src


def inline_images(html: str, base_dir: str | None = None) -> str:
    """Replace every src='...' in HTML with its base64 data URI."""
    def _replace(match):
        return f'src="{image_data_uri(match.group(1), base_dir=base_dir)}"'
    return re.sub(r"""src=["']([^"']+)["']""", _replace, html)


# ---------------------------------------------------------------------------
# Clipboard helper (WSL clip.exe, Linux xclip / xsel / wl-copy)
# ---------------------------------------------------------------------------

def copy_to_clipboard(text: str) -> bool:
    """
    Copies text to system clipboard.
    Works across WSL (clip.exe), X11 (xclip / xsel), and Wayland (wl-copy).
    Returns True if copied to at least one clipboard.
    """
    copied = False

    # 1. WSL clip.exe (copies to Windows host clipboard)
    if shutil.which("clip.exe"):
        try:
            subprocess.run(
                ["clip.exe"],
                input=text.encode("utf-16le"),
                check=True,
                stderr=subprocess.DEVNULL,
            )
            copied = True
        except Exception as e:
            log.debug("clip.exe failed: %s", e)

    # 2. Linux X11 xclip
    if shutil.which("xclip"):
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode("utf-8"),
                check=True,
                stderr=subprocess.DEVNULL,
            )
            copied = True
        except Exception as e:
            log.debug("xclip failed: %s", e)

    # 3. Linux X11 xsel
    if shutil.which("xsel"):
        try:
            subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=text.encode("utf-8"),
                check=True,
                stderr=subprocess.DEVNULL,
            )
            copied = True
        except Exception as e:
            log.debug("xsel failed: %s", e)

    # 4. Wayland wl-copy
    if shutil.which("wl-copy"):
        try:
            subprocess.run(
                ["wl-copy"],
                input=text.encode("utf-8"),
                check=True,
                stderr=subprocess.DEVNULL,
            )
            copied = True
        except Exception as e:
            log.debug("wl-copy failed: %s", e)

    return copied


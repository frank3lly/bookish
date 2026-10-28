"""
Centralized configuration and path constants for Bookish.

All paths, URLs, and shared settings live here so every module imports
from one place instead of recomputing them independently.
"""

import os
import logging

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# PROJECT_ROOT is the repo root (parent of bookish_pkg/)
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)

# Automatically load .env if present in PROJECT_ROOT or ~/.config/bookish/env
_env_candidates = [
    os.path.join(PROJECT_ROOT, ".env"),
    os.path.join(os.path.expanduser("~"), ".config", "bookish", "env"),
]
for _env_path in _env_candidates:
    if os.path.exists(_env_path):
        try:
            with open(_env_path, "r", encoding="utf-8") as _ef:
                for _line in _ef:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _v = _line.split("=", 1)
                        _k, _v = _k.strip(), _v.strip().strip("'\"")
                        if _k and _k not in os.environ:
                            os.environ[_k] = _v
        except Exception:
            pass

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DRAFTS_DIR = os.path.join(DATA_DIR, "drafts")
ATTACHMENTS_DIR = os.path.join(DATA_DIR, "attachments")
HANDOFF_DIR = os.path.join(DATA_DIR, "agent_handoff")
ASSIGNMENTS_FILE = os.path.join(DATA_DIR, "assignments.json")
STATE_FILE = os.path.join(PROJECT_ROOT, "state.json")
CONVERTER_FORMAT_FILE = os.path.join(PROJECT_ROOT, "CONVERTER_FORMAT.md")

# Output directory -- configurable via BOOKISH_OUTPUT_DIR env var
_user_downloads = os.path.join(os.path.expanduser("~"), "Downloads", "bookish")
# If running under WSL without explicit BOOKISH_OUTPUT_DIR, check Windows user Downloads
if "BOOKISH_OUTPUT_DIR" not in os.environ and os.path.isdir("/mnt/c/Users"):
    try:
        for _u in os.listdir("/mnt/c/Users"):
            if _u not in ("Public", "Default", "Default User", "All Users"):
                _win_dl = os.path.join("/mnt/c/Users", _u, "Downloads", "bookish")
                if os.path.isdir(os.path.dirname(_win_dl)):
                    _user_downloads = _win_dl
                    break
    except Exception:
        pass

DEFAULT_OUTPUT_DIR = os.environ.get("BOOKISH_OUTPUT_DIR", _user_downloads)
PDFS_DIR = DEFAULT_OUTPUT_DIR
PRESENTATIONS_DIR = DEFAULT_OUTPUT_DIR

# ---------------------------------------------------------------------------
# Moodle URLs
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("BOOKISH_MOODLE_URL", "https://moodle.uce.edu.do")
LOGIN_URL = f"{BASE_URL}/login/index.php"
CALENDAR_URL = f"{BASE_URL}/calendar/view.php?view=month"

# ---------------------------------------------------------------------------
# Student defaults (configurable via env vars)
# ---------------------------------------------------------------------------
STUDENT_NAME = os.environ.get("BOOKISH_STUDENT_NAME", "Estudiante")
STUDENT_ENROLMENT = os.environ.get("BOOKISH_STUDENT_ENROLMENT", "2024-0000")

# ---------------------------------------------------------------------------
# Moodle overlay suppression JS (reused by login and scraper)
# ---------------------------------------------------------------------------
MOODLE_SESSION_STORAGE_JS = """() => {
    try {
        sessionStorage.setItem('qr_encuesta_visto', '1');
        sessionStorage.setItem('encuesta_visto', '1');
        sessionStorage.setItem('aviso_visto', '1');
        sessionStorage.setItem('cookie_accepted', '1');
    } catch(e) {}
}"""

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger for Bookish."""
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )

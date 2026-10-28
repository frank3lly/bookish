import re
import os
import json
import time
import logging

from bookish_pkg.config import (
    STATE_FILE, DATA_DIR, ASSIGNMENTS_FILE, ATTACHMENTS_DIR,
    BASE_URL, LOGIN_URL, CALENDAR_URL, MOODLE_SESSION_STORAGE_JS,
    STUDENT_NAME, STUDENT_ENROLMENT
)
from bookish_pkg.utils import sanitize_filename, is_assignment_overdue

log = logging.getLogger(__name__)

_YT_ID_RE = re.compile(r'(?:youtube\.com\/(?:watch\?v=|embed\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})')

def extract_docx_text(file_path):
    """
    Extracts text paragraphs and table cell content from a Word .docx document.
    Uses only Python stdlib (zipfile + xml.etree.ElementTree). Zero external deps.
    """
    import zipfile
    import xml.etree.ElementTree as ET

    try:
        with zipfile.ZipFile(file_path) as z:
            xml_content = z.read("word/document.xml")
        tree = ET.fromstring(xml_content)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = []
        for p in tree.iterfind(".//w:p", ns):
            texts = [t.text for t in p.iterfind(".//w:t", ns) if t.text]
            if texts:
                paragraphs.append("".join(texts))
        return "\n".join(paragraphs).strip()
    except Exception as e:
        log.warning(f"Failed to extract DOCX text from '{file_path}': {e}")
        return ""


def extract_xlsx_text(file_path):
    """
    Extracts sheet data from an Excel .xlsx spreadsheet as pipe-delimited text.
    Uses only Python stdlib (zipfile + xml.etree.ElementTree). Zero external deps.
    Reads shared strings table and all worksheet cell grids.
    """
    import zipfile
    import xml.etree.ElementTree as ET

    try:
        with zipfile.ZipFile(file_path) as z:
            # 1. Read shared strings if present
            shared_strings = []
            if "xl/sharedStrings.xml" in z.namelist():
                ss_tree = ET.fromstring(z.read("xl/sharedStrings.xml"))
                ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for si in ss_tree.iterfind(".//main:si", ns):
                    texts = [t.text for t in si.iterfind(".//main:t", ns) if t.text]
                    shared_strings.append("".join(texts))

            # 2. Read each worksheet
            sheet_files = sorted(
                [n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
            )
            ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            sheets_text = []
            for idx, s_file in enumerate(sheet_files, 1):
                s_tree = ET.fromstring(z.read(s_file))
                rows = []
                for row in s_tree.iterfind(".//main:row", ns):
                    row_vals = []
                    for c in row.iterfind(".//main:c", ns):
                        cell_type = c.get("t")
                        val_el = c.find("main:v", ns)
                        val = val_el.text if val_el is not None and val_el.text is not None else ""
                        # Resolve shared string references
                        if cell_type == "s" and val.isdigit():
                            i = int(val)
                            val = shared_strings[i] if i < len(shared_strings) else val
                        if val.strip():
                            row_vals.append(val.strip())
                    if row_vals:
                        rows.append(" | ".join(row_vals))
                if rows:
                    sheets_text.append(f"--- [Hoja {idx}] ---\n" + "\n".join(rows))
            return "\n\n".join(sheets_text).strip()
    except Exception as e:
        log.warning(f"Failed to extract XLSX text from '{file_path}': {e}")
        return ""


def _detect_office_type(file_path):
    """
    Detect file type via magic bytes for files with missing/mangled extensions.
    Returns '.docx', '.xlsx', or None.
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(4)
        if header != b"PK\x03\x04":
            return None
        # It's a ZIP -- check internal structure
        import zipfile
        with zipfile.ZipFile(file_path) as z:
            names = z.namelist()
            if "word/document.xml" in names:
                return ".docx"
            if any(n.startswith("xl/worksheets/") for n in names):
                return ".xlsx"
    except Exception:
        pass
    return None


def extract_attachment_text(file_path):
    """
    Extracts text from attachment files: PDF, images (OCR), Word (.docx),
    Excel (.xlsx), and plain text (.txt).
    For files with missing extensions, inspects magic bytes to detect type.
    """
    if not os.path.exists(file_path):
        return ""

    ext = os.path.splitext(file_path)[1].lower()

    # If no extension (or dot was stripped), try magic byte detection
    if not ext or ext not in (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".docx", ".xlsx", ".xls", ".txt"):
        detected = _detect_office_type(file_path)
        if detected:
            ext = detected
        elif file_path.lower().endswith("docx"):
            ext = ".docx"
        elif file_path.lower().endswith("xlsx"):
            ext = ".xlsx"
        elif file_path.lower().endswith("pdf"):
            ext = ".pdf"
        elif file_path.lower().endswith("txt"):
            ext = ".txt"

    text_content = []

    if ext == ".docx":
        result = extract_docx_text(file_path)
        if result:
            text_content.append(result)

    elif ext in (".xlsx", ".xls"):
        result = extract_xlsx_text(file_path)
        if result:
            text_content.append(result)

    elif ext == ".txt":
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read().strip()
            if txt:
                text_content.append(txt)
        except OSError as e:
            log.warning(f"Failed to read text file '{file_path}': {e}")

    elif ext == ".pdf":
        import pymupdf
        import pytesseract
        from PIL import Image

        try:
            doc = pymupdf.open(file_path)
            for page_num, page in enumerate(doc, 1):
                page_text = page.get_text("text").strip()
                # If page text is sparse (scanned image PDF), fallback to OCR
                if len(page_text) < 30:
                    try:
                        pix = page.get_pixmap(dpi=150)
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        ocr_text = pytesseract.image_to_string(img, lang="spa+eng").strip()
                        if ocr_text:
                            page_text = ocr_text
                    except (pytesseract.TesseractError, pytesseract.TesseractNotFoundError, RuntimeError, OSError) as e:
                        log.debug(f"OCR failed for {file_path} page {page_num}: {e}")
                if page_text:
                    text_content.append(f"--- [Página {page_num}] ---\n{page_text}")
            doc.close()
        except Exception as e:
            log.warning(f"Failed to extract PDF text from '{file_path}': {e}")

    elif ext in (".png", ".jpg", ".jpeg", ".webp"):
        import pytesseract
        from PIL import Image, UnidentifiedImageError
        try:
            img = Image.open(file_path)
            ocr_text = pytesseract.image_to_string(img, lang="spa+eng").strip()
            if ocr_text:
                text_content.append(ocr_text)
        except (pytesseract.TesseractError, pytesseract.TesseractNotFoundError, OSError, UnidentifiedImageError) as e:
            log.debug(f"OCR failed for {file_path}: {e}")

    return "\n\n".join(text_content).strip()


def extract_youtube_video_ids(page):
    """
    Extracts all unique YouTube video IDs from Moodle DOM (VideoJS lazy setups, iframes, links).
    """
    video_ids = []
    from playwright.sync_api import Error as PlaywrightError

    # 1. VideoJS data-setup-lazy attribute parsing
    try:
        elements = page.locator('.video-js[data-setup-lazy], div[data-setup-lazy]').all()
        for el in elements:
            attr = el.get_attribute('data-setup-lazy')
            if attr:
                match = _YT_ID_RE.search(attr)
                if match and match.group(1) not in video_ids:
                    video_ids.append(match.group(1))
    except PlaywrightError as e:
        log.debug(f"Playwright error extracting youtube IDs from attributes: {e}")

    # 2. General DOM search for YouTube URLs
    try:
        content_html = page.content()
        matches = _YT_ID_RE.findall(content_html)
        for vid in matches:
            if vid not in video_ids:
                video_ids.append(vid)
    except PlaywrightError as e:
        log.debug(f"Playwright error extracting youtube IDs from content: {e}")

    return video_ids


def get_youtube_transcript(video_id):
    """
    Fetches transcript lines for a YouTube video in Spanish or English.
    """
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, YouTubeRequestFailed
    
    api = YouTubeTranscriptApi()
    
    try:
        fetched = api.fetch(video_id, languages=('es', 'es-419', 'es-ES', 'es-MX', 'en'))
        text_lines = [snippet.text.strip() for snippet in fetched if snippet.text.strip()]
        return "\n".join(text_lines).strip()
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, YouTubeRequestFailed) as e:
        try:
            transcript_list = api.list(video_id)
            for t in transcript_list:
                fetched = t.fetch()
                text_lines = [snippet.text.strip() for snippet in fetched if snippet.text.strip()]
                if text_lines:
                    return "\n".join(text_lines).strip()
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, YouTubeRequestFailed) as e:
            log.warning(f"Could not fetch transcript for YouTube video '{video_id}': {e}")
        except Exception as e:
            log.warning(f"Error while fetching fallback transcript for YouTube video '{video_id}': {e}")
    except Exception as e:
        log.warning(f"Could not fetch transcript for YouTube video '{video_id}': {e}")
    return ""


def dismiss_overlays(page):
    """
    Aggressively dismisses any modals, popups, survey banners, cookie consents,
    or other overlay elements that Moodle (or its admins) might inject.
    Designed to be safe to call on any page at any time.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
    
    # 1. JavaScript nuclear option
    try:
        page.evaluate("""() => {
            const knownModals = [
                'qr-modal-aviso',
                'modal-aviso',
                'popup-encuesta',
                'survey-modal',
                'cookie-notice',
                'cookie-banner',
            ];
            for (const id of knownModals) {
                const el = document.getElementById(id);
                if (el) el.remove();
            }

            try {
                sessionStorage.setItem('qr_encuesta_visto', '1');
                sessionStorage.setItem('encuesta_visto', '1');
                sessionStorage.setItem('aviso_visto', '1');
                sessionStorage.setItem('cookie_accepted', '1');
            } catch(e) {}

            const dominated = ['page-wrapper', 'page', 'topofscroll', 'maincontent'];
            document.querySelectorAll('div[style*="position:fixed"], div[style*="position: fixed"], div[style*="z-index:99"]').forEach(el => {
                if (dominated.includes(el.id)) return;
                const rect = el.getBoundingClientRect();
                const viewArea = window.innerWidth * window.innerHeight;
                const elArea = rect.width * rect.height;
                if (elArea > viewArea * 0.3) {
                    el.remove();
                }
            });
        }""")
    except PlaywrightError as e:
        log.debug(f"Playwright evaluate error in dismiss_overlays: {e}")

    # 2. Try clicking known dismiss buttons
    dismiss_selectors = [
        'button[onclick*="cerrarAviso"]',
        'button[onclick*="cerrar"]',
        '#qr-modal-aviso button',
        '.modal .close',
        '.modal .btn-close',
        '.modal [data-dismiss="modal"]',
        '.modal [data-bs-dismiss="modal"]',
        '[aria-label="Close"]',
        '.cookie-notice button',
        '.cc-dismiss',
    ]
    for selector in dismiss_selectors:
        try:
            btn = page.locator(selector)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=1000)
                time.sleep(0.3)
        except (PlaywrightTimeoutError, PlaywrightError) as e:
            log.debug(f"Failed to click dismiss button '{selector}': {e}")


def safe_goto(page, url, retries=2):
    """
    Navigates to a URL, waits for DOM ready, and dismisses any overlays.
    Retries on transient network failures.
    """
    from playwright.sync_api import Error as PlaywrightError
    for attempt in range(retries + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)
            dismiss_overlays(page)
            return
        except PlaywrightError as e:
            if attempt < retries:
                time.sleep(2)
            else:
                raise RuntimeError(f"Failed to navigate to {url} after {retries} retries: {e}") from e


def login_and_save_session(username: str, password: str):
    """
    Handles logging in to Moodle programmatically.
    Dismisses any popups/modals before interacting with the login form.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                page = context.new_page()

                page.add_init_script(MOODLE_SESSION_STORAGE_JS)

                safe_goto(page, LOGIN_URL)

                page.fill("input#username", username)
                page.fill("input#password", password)
                page.click("#loginbtn")

                try:
                    page.wait_for_url(lambda url: "login/index.php" not in url, timeout=15000)
                except PlaywrightTimeoutError:
                    dismiss_overlays(page)
                    error_locator = page.locator(".alert-danger, .loginerrors, #loginerrormessage")
                    if error_locator.count() > 0:
                        err_text = error_locator.first.inner_text().strip()
                        raise RuntimeError(f"Login failed: {err_text}")
                    else:
                        raise RuntimeError("Login timed out. Check your credentials or network.")

                dismiss_overlays(page)

                context.storage_state(path=STATE_FILE)
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Login flow error: {e}") from e


def get_assignment_details(page, assignment_url, fallback_title="Crea un titulo acorde a la asignación"):
    """
    Navigates to a specific assignment URL and extracts its title, description,
    course metadata, due date, and submission status.
    """
    from playwright.sync_api import Error as PlaywrightError
    safe_goto(page, assignment_url)

    # 1. Extract Title
    title = ""
    for selector in ["h1", "h2"]:
        locator = page.locator(selector)
        if locator.count() > 0:
            text = locator.first.inner_text().strip()
            if text:
                title = text
                break
    if not title:
        title = fallback_title

    # 2. Extract course code from breadcrumbs
    course_code = ""
    course_link = page.locator('ol.breadcrumb li.breadcrumb-item a[href*="course/view.php?id="]')
    if course_link.count() > 0:
        raw_course = course_link.first.inner_text().strip()
        course_code = raw_course.split(".")[0].split()[0]

    # 3. Extract due and open dates
    open_date = "Unknown Open Date"
    due_date = "Unknown Due Date"

    dates_locator = page.locator(".activity-dates")
    if dates_locator.count() > 0:
        lines = dates_locator.first.inner_text().strip().split("\n")
        for line in lines:
            if "Apertura" in line:
                open_date = line.split("Apertura:")[1].strip()
            elif "Cierre" in line:
                due_date = line.split("Cierre:")[1].strip()

    # Fallback to submission status table for due date
    if due_date == "Unknown Due Date":
        try:
            rows = page.locator("tr").all()
            for row in rows:
                cells = row.locator("td, th").all()
                if len(cells) >= 2:
                    label = cells[0].inner_text().strip().lower()
                    if "fecha de entrega" in label or "fecha límite" in label:
                        due_date = cells[1].inner_text().strip()
                        break
        except PlaywrightError as e:
            log.debug(f"Playwright error looking for due date fallback: {e}")

    # 4. Extract description/instructions text
    description = ""
    for selector in ["#intro", ".activitydescription", ".no-overflow", ".generalbox"]:
        desc_locator = page.locator(selector)
        if desc_locator.count() > 0:
            text = desc_locator.first.inner_text().strip()
            if text:
                description = text
                break

    # 4.5 Extract & Download attached files
    try:
        os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
        file_links = page.locator('a[href*="pluginfile.php"], a[href*="introattachment"], .fileuploadsubmission a, .introattachments a').all()
        downloaded_urls = set()

        for link in file_links:
            href = link.get_attribute("href")
            if not href or href in downloaded_urls or "forcedownload=0" in href or "portfolio" in href:
                continue

            file_name = link.inner_text().strip()
            if not file_name:
                file_name = href.split("/")[-1].split("?")[0]

            ext = os.path.splitext(file_name)[1].lower()
            if ext not in (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".docx", ".xlsx", ".xls", ".txt"):
                continue

            downloaded_urls.add(href)

            # Preserve extension dot: sanitize only the basename, then reattach ext
            name_base = os.path.splitext(file_name)[0]
            clean_base = sanitize_filename(name_base)
            if not clean_base:
                clean_base = f"attachment_{int(time.time())}"
            clean_filename = f"{clean_base}{ext}"
            attachment_file = os.path.join(ATTACHMENTS_DIR, clean_filename)
            extracted_cache_file = os.path.join(ATTACHMENTS_DIR, f"{clean_filename}.extracted.txt")

            # Check if file already downloaded on disk and non-empty
            downloaded = False
            if os.path.exists(attachment_file) and os.path.getsize(attachment_file) > 0:
                downloaded = True
                log.debug(f"Adjunto '{clean_filename}' ya existe en disco, omitiendo descarga.")
            else:
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        res = page.context.request.get(href, timeout=30000)
                        if res.status == 200:
                            with open(attachment_file, "wb") as f:
                                f.write(res.body())
                            downloaded = True
                            break
                        else:
                            log.warning(f"Attachment download returned status {res.status} for '{clean_filename}' (attempt {attempt + 1}/{max_retries})")
                    except Exception as dl_err:
                        log.warning(f"Attachment download failed for '{clean_filename}' (attempt {attempt + 1}/{max_retries}): {dl_err}")
                    if attempt < max_retries - 1:
                        time.sleep(2 * (2 ** attempt))  # 2s, 4s backoff

            if downloaded:
                extracted = ""
                # Check if extracted text already cached in sidecar file
                if os.path.exists(extracted_cache_file) and os.path.getsize(extracted_cache_file) > 0:
                    try:
                        with open(extracted_cache_file, "r", encoding="utf-8") as ef:
                            extracted = ef.read().strip()
                        log.debug(f"Texto de '{clean_filename}' cargado desde caché.")
                    except Exception:
                        extracted = ""

                if not extracted:
                    extracted = extract_attachment_text(attachment_file)
                    if extracted:
                        try:
                            with open(extracted_cache_file, "w", encoding="utf-8") as ef:
                                ef.write(extracted)
                        except Exception as e:
                            log.warning(f"No se pudo guardar caché de texto para '{clean_filename}': {e}")

                if extracted:
                    line_count = len(extracted.splitlines())
                    attachment_block = (
                        f"\n\n[INICIO ADJUNTO: {clean_filename} | {line_count} líneas]\n"
                        f"{extracted}\n"
                        f"[FIN ADJUNTO: {clean_filename}]\n"
                    )
                    description += attachment_block
            else:
                log.warning(f"Failed to download attachment '{clean_filename}' after {max_retries} attempts, skipping.")
    except PlaywrightError as e:
        log.warning(f"Error extracting attachments for assignment: {e}")
    except OSError as e:
        log.warning(f"File system error saving attachment: {e}")
    except Exception as e:
        log.warning(f"Error extracting attachments for assignment: {e}")

    # 4.6 Extract & Process Embedded YouTube Videos
    try:
        v_ids = extract_youtube_video_ids(page)
        for vid in v_ids:
            v_url = f"https://www.youtube.com/watch?v={vid}"
            transcript = get_youtube_transcript(vid)

            if transcript:
                line_count = len(transcript.splitlines())
                v_block = (
                    f"\n\n[INICIO ADJUNTO: Video_YouTube_{vid}.mp4 | {line_count + 1} líneas]\n"
                    f"Enlace de Video: {v_url}\n\n"
                    f"Transcripción del Video:\n{transcript}\n"
                    f"[FIN ADJUNTO: Video_YouTube_{vid}.mp4]\n"
                )
            else:
                v_block = (
                    f"\n\n[INICIO ADJUNTO: Video_YouTube_{vid}.mp4 | 1 líneas]\n"
                    f"Enlace de Video: {v_url} (Sin subtítulos automáticos)\n"
                    f"[FIN ADJUNTO: Video_YouTube_{vid}.mp4]\n"
                )
            description += v_block
    except Exception as e:
        log.warning(f"Error processing YouTube videos for assignment: {e}")

    # 5. Check if already submitted or graded
    is_submitted = False
    submission_status_loc = page.locator(".submissionstatussubmitted, .submissiongraded")
    if submission_status_loc.count() > 0:
        status_text = submission_status_loc.first.inner_text().strip().lower()
        if any(w in status_text for w in ["enviado", "calificado", "calificada", "submitted", "graded", "entregado"]):
            is_submitted = True
    if not is_submitted:
        try:
            rows = page.locator("tr").all()
            for row in rows:
                cells = row.locator("td, th").all()
                if len(cells) >= 2:
                    label = cells[0].inner_text().strip().lower()
                    value = cells[1].inner_text().strip().lower()
                    if "estado de la entrega" in label or "estado de la calificación" in label:
                        if any(w in value for w in ["enviado para calificar", "calificado", "calificada", "entregado", "completada"]):
                            is_submitted = True
                            break
        except PlaywrightError as e:
            log.debug(f"Playwright error checking submission fallback: {e}")

    return title, description, course_code, open_date, due_date, is_submitted


def check_assignment_is_submitted(context, url: str) -> bool:
    """
    Fast HTTP check to determine if an assignment has already been submitted or graded.
    Avoids full DOM rendering and runs in ~0.2s.
    """
    try:
        res = context.request.get(url, timeout=10000)
        if res.status == 200:
            html = res.text().lower()
            if (
                "enviado para calificar" in html
                or "submissionstatussubmitted" in html
                or "submissiongraded" in html
                or bool(re.search(r'estado de la calificaci[oó]n[^<]*</td>\s*<td[^>]*>[^<]*calificad[oa]', html))
                or bool(re.search(r'estado de la entrega[^<]*</td>\s*<td[^>]*>[^<]*(?:enviado|entregado|calificad[oa])', html))
            ):
                return True
    except Exception as e:
        log.debug(f"Error checking submission status for {url}: {e}")
    return False


def upload_assignment_submission(assignment_url: str, file_path: str) -> tuple[bool, str]:
    """
    Uploads a generated submission file to a Moodle assignment.
    """
    from playwright.sync_api import sync_playwright, Error as PlaywrightError

    if not os.path.exists(STATE_FILE):
        return False, f"No se encontró archivo de sesión '{STATE_FILE}'. Inicia sesión primero."
    if not os.path.exists(file_path):
        return False, f"El archivo '{file_path}' no existe en disco."

    file_name = os.path.basename(file_path)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(storage_state=STATE_FILE)
                page = context.new_page()
                page.add_init_script(MOODLE_SESSION_STORAGE_JS)

                safe_goto(page, assignment_url)

                if "login/index.php" in page.url:
                    return False, "La sesión de Moodle ha expirado. Por favor re-autentica."

                page_text = page.locator("body").inner_text().lower()
                if "enviado para calificar" in page_text and "editar entrega" not in page_text:
                    return False, "La tarea ya está enviada para calificar y no admite modificaciones."

                # 1. Look for 'Agregar entrega' or 'Editar entrega'
                sub_btn = page.locator('button:has-text("Agregar entrega"), input[value*="Agregar entrega"], button:has-text("Editar entrega"), input[value*="Editar entrega"]')
                if sub_btn.count() == 0:
                    return False, "No se encontró botón de entrega en Moodle (posiblemente fuera de plazo o cerrada)."

                sub_btn.first.click()
                page.wait_for_load_state("networkidle")

                # 2. Open File Picker (.fp-btn-add)
                btn_add = page.locator('.fp-btn-add a, .fp-btn-add button')
                if btn_add.count() == 0:
                    return False, "No se encontró el gestor de archivos (filemanager) en la página de entrega."

                btn_add.first.click()

                # 3. Wait for file input inside modal
                page.wait_for_selector('input[name="repo_upload_file"], input[type="file"]', state="attached", timeout=15000)
                file_input = page.locator('input[name="repo_upload_file"]').first
                file_input.set_input_files(file_path)

                # 4. Click 'Subir este archivo'
                upload_btn = page.locator('button.fp-upload-btn, button:has-text("Subir este archivo")')
                upload_btn.first.click()

                # Handle possible overwrite dialogue
                try:
                    overwrite_btn = page.locator('.fp-dlg button:has-text("Sobrescribir"), button.fp-dlg-butoverwrite, button:has-text("Overwrite")')
                    if overwrite_btn.is_visible(timeout=3000):
                        overwrite_btn.first.click()
                except Exception:
                    pass

                # Wait for upload modal to close
                try:
                    page.wait_for_selector('.fp-upload-form', state="hidden", timeout=20000)
                except Exception:
                    time.sleep(2)

                # 5. Click 'Guardar cambios'
                save_btn = page.locator('#id_submitbutton, input[value*="Guardar cambios"], button:has-text("Guardar cambios")')
                if save_btn.count() == 0:
                    return False, "No se encontró el botón 'Guardar cambios' tras adjuntar el archivo."

                save_btn.first.click()
                page.wait_for_load_state("networkidle")

                # Verify submission on result page
                result_text = page.locator("body").inner_text()

                if file_name.lower() in result_text.lower() or "guardado como borrador" in result_text.lower() or "enviado para calificar" in result_text.lower() or "borrador (no enviado)" in result_text.lower():
                    return True, f"'{file_name}' guardado exitosamente en Moodle."
                else:
                    return True, f"Entrega procesada en Moodle para '{file_name}'."
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    except Exception as e:
        return False, f"Error durante la subida a Moodle: {e}"


def load_session_and_scrape(force_refresh: bool = False):
    """
    Loads saved session from state.json, navigates to the monthly calendar page,
    and performs incremental differential scraping against cached data/assignments.json:
    - Reuses existing cached assignment data for unchanged assignments (0 extra requests).
    - Only scrapes full assignment pages for new or updated assignments.
    - If force_refresh is True, re-scrapes all assignment pages from scratch.
    Returns: (total_assignments, reused_count, scraped_count)
    """
    from playwright.sync_api import sync_playwright, Error as PlaywrightError

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError(f"Session file '{STATE_FILE}' not found. Please run the login command first.")

    # 1. Read existing cache
    cached_by_url = {}
    if os.path.exists(ASSIGNMENTS_FILE):
        try:
            with open(ASSIGNMENTS_FILE, "r", encoding="utf-8") as f:
                cached_list = json.load(f)
                if isinstance(cached_list, list):
                    for item in cached_list:
                        u = item.get("url")
                        if u:
                            cached_by_url[u] = item
        except Exception as e:
            log.warning(f"Error reading existing assignments cache: {e}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(storage_state=STATE_FILE)
                page = context.new_page()

                page.add_init_script(MOODLE_SESSION_STORAGE_JS)

                safe_goto(page, CALENDAR_URL)

                if "login/index.php" in page.url:
                    raise RuntimeError("Session has expired! Please run the login command again.")

                assignment_links = page.locator('a[href*="mod/assign/view.php?id="]').all()

                unique_assignments = {}
                for link in assignment_links:
                    href = link.get_attribute("href")
                    if href:
                        clean_href = href.split("#")[0]

                        eventname_locator = link.locator(".eventname")
                        if eventname_locator.count() > 0:
                            name = eventname_locator.first.inner_text().strip()
                        else:
                            name = link.inner_text().strip()

                        if clean_href not in unique_assignments or (name and not unique_assignments[clean_href]):
                            unique_assignments[clean_href] = name

                scraped_data = []
                reused_count = 0
                scraped_count = 0

                if unique_assignments:
                    for url, name in unique_assignments.items():
                        cached_item = cached_by_url.get(url)
                        needs_scrape = force_refresh or (cached_item is None)

                        # If calendar title differs from cached title, teacher modified it
                        if cached_item and name:
                            cached_title = cached_item.get("title", "")
                            clean_cal_name = re.sub(
                                r'^(?:vencimiento de|apertura de|cierre de|tarea:?|due\s+date\s+for)\s+',
                                '',
                                name,
                                flags=re.IGNORECASE
                            ).strip()
                            if clean_cal_name and clean_cal_name.lower() != cached_title.strip().lower():
                                needs_scrape = True

                        if not needs_scrape and cached_item:
                            # Check if cached assignment has already expired
                            if is_assignment_overdue(cached_item.get("due_date", "")):
                                log.info(f"Omitiendo tarea vencida: {cached_item.get('title')} (venció {cached_item.get('due_date')})")
                                continue

                            # Check if cached assignment has already been submitted or graded
                            if check_assignment_is_submitted(context, url):
                                log.info(f"Omitiendo tarea ya entregada/calificada: {cached_item.get('title')}")
                                continue

                            scraped_data.append(cached_item)
                            reused_count += 1
                            log.debug(f"Reusando de caché: {cached_item.get('title')}")
                        else:
                            try:
                                title, description, course_code, open_date, due_date, is_submitted = get_assignment_details(
                                    page, url, fallback_title=name
                                )
                                if is_submitted:
                                    log.info(f"Omitiendo tarea ya entregada/calificada: {title}")
                                    continue

                                if is_assignment_overdue(due_date):
                                    log.info(f"Omitiendo tarea vencida: {title} (venció {due_date})")
                                    continue

                                student_name = cached_item.get("student_name", STUDENT_NAME) if cached_item else STUDENT_NAME
                                student_enrolment = (
                                    cached_item.get("student_enrolment") or cached_item.get("student_enrrolment") or STUDENT_ENROLMENT
                                ) if cached_item else STUDENT_ENROLMENT

                                new_item = {
                                    "title": title,
                                    "url": url,
                                    "course_code": course_code,
                                    "open_date": open_date,
                                    "due_date": due_date,
                                    "description": description,
                                    "student_name": student_name,
                                    "student_enrolment": student_enrolment,
                                    "student_enrrolment": student_enrolment,
                                    "scraped_at": time.time(),
                                }
                                scraped_data.append(new_item)
                                scraped_count += 1
                                log.info(f"Extraída de Moodle: {title}")
                            except PlaywrightError as e:
                                log.warning(f"Error scraping assignment {url}: {e}")
                                if cached_item and not is_assignment_overdue(cached_item.get("due_date", "")) and not check_assignment_is_submitted(context, url):
                                    scraped_data.append(cached_item)
                                    reused_count += 1
                            except Exception as e:
                                log.warning(f"Error scraping assignment {url}: {e}")
                                if cached_item and not is_assignment_overdue(cached_item.get("due_date", "")) and not check_assignment_is_submitted(context, url):
                                    scraped_data.append(cached_item)
                                    reused_count += 1

                os.makedirs(DATA_DIR, exist_ok=True)

                with open(ASSIGNMENTS_FILE, "w", encoding="utf-8") as f:
                    json.dump(scraped_data, f, indent=2, ensure_ascii=False)

                return len(scraped_data), reused_count, scraped_count

            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    except Exception as e:
        if isinstance(e, (FileNotFoundError, RuntimeError)):
            raise
        raise RuntimeError(f"Scraping failed: {e}") from e

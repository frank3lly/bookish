import os
import sys
import re
import json
import time
import shutil
import curses
import subprocess
import logging

from bookish_pkg.config import (
    DRAFTS_DIR, PDFS_DIR, PRESENTATIONS_DIR, DEFAULT_OUTPUT_DIR,
    HANDOFF_DIR, CONVERTER_FORMAT_FILE, ASSIGNMENTS_FILE, PROJECT_ROOT,
    STUDENT_NAME, STUDENT_ENROLMENT, STATE_FILE,
)
from bookish_pkg.utils import sanitize_filename, build_cover_page_html, copy_to_clipboard, is_assignment_overdue
from bookish_pkg.scraper import login_and_save_session, load_session_and_scrape, upload_assignment_submission
from bookish_pkg.generator import curses_prompt_assignment, generate_assignment_draft
from bookish_pkg.converter import convert_md_to_pdf, render_presentation_png

log = logging.getLogger(__name__)

BOOKISH_BANNER = [
    "██████╗  ██████╗  ██████╗ ██╗  ██╗██╗███████╗██╗  ██╗",
    "██╔══██╗██╔═══██╗██╔═══██╗██║ ██╔╝██║██╔════╝██║  ██║",
    "██████╔╝██║   ██║██║   ██║█████╔╝ ██║███████╗███████║",
    "██╔══██╗██║   ██║██║   ██║██╔═██╗ ██║╚════██║██╔══██║",
    "██████╔╝╚██████╔╝╚██████╔╝██║  ██╗██║███████║██║  ██║",
    "╚═════╝  ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝╚══════╝╚═╝  ╚═╝",
]


class BookishLogger:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.logs = []
        self.had_error = False
        self.show_splash = True
        self.progress_percent = 0
        self.progress_message = "Iniciando Bookish..."
        self.init_colors()

    def init_colors(self):
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
            curses.init_pair(2, curses.COLOR_GREEN, -1)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)
            curses.init_pair(4, curses.COLOR_RED, -1)
            curses.init_pair(5, curses.COLOR_CYAN, -1)
            curses.init_pair(6, curses.COLOR_BLUE, -1)
        except Exception:
            pass

    def set_progress(self, percent: int, message: str):
        self.progress_percent = max(0, min(100, percent))
        self.progress_message = message
        self.log(f"{percent}% - {message}", category="step")
        if self.show_splash and not self.had_error:
            self.render_splash()

    def log(self, message, category="info"):
        timestamp = time.strftime("%H:%M:%S")
        self.logs.append((timestamp, message, category))
        log.info(f"[{category.upper()}] {message}")
        if category == "error":
            self.had_error = True
            self.show_splash = False
            self.render()
        elif self.show_splash and not self.had_error:
            self.render_splash()
        else:
            self.render()

    def render_splash(self):
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        if height < 10 or width < 40:
            self.stdscr.addstr(0, 0, "Bookish - Cargando...", curses.A_BOLD)
            self.stdscr.refresh()
            return

        banner_w = len(BOOKISH_BANNER[0])
        banner_h = len(BOOKISH_BANNER)
        total_content_h = banner_h + 6
        start_y = max(1, (height - total_content_h) // 2)

        blue_attr = curses.color_pair(6) | curses.A_BOLD
        if width >= banner_w + 2:
            start_x = (width - banner_w) // 2
            for idx, line in enumerate(BOOKISH_BANNER):
                y = start_y + idx
                if y < height - 5:
                    self.stdscr.attron(blue_attr)
                    self.stdscr.addstr(y, start_x, line)
                    self.stdscr.attroff(blue_attr)
            sub_y = start_y + banner_h + 1
        else:
            compact = "== BOOKISH =="
            self.stdscr.attron(blue_attr)
            self.stdscr.addstr(start_y, max(0, (width - len(compact)) // 2), compact)
            self.stdscr.attroff(blue_attr)
            sub_y = start_y + 2

        # Subtitle
        subtitle = "continuous improvement, every day."
        if sub_y < height - 4:
            sub_attr = curses.color_pair(5) | curses.A_DIM
            sub_x = max(0, (width - len(subtitle)) // 2)
            self.stdscr.attron(sub_attr)
            self.stdscr.addstr(sub_y, sub_x, subtitle)
            self.stdscr.attroff(sub_attr)

        # Progress bar
        bar_y = sub_y + 3
        if bar_y < height - 1:
            bar_width = min(36, max(12, width - 20))
            filled = int((self.progress_percent / 100) * bar_width)
            empty = bar_width - filled
            bar_str = f"[{'█' * filled}{'░' * empty}] {self.progress_percent}%"
            bar_x = max(0, (width - len(bar_str)) // 2)

            self.stdscr.attron(blue_attr)
            self.stdscr.addstr(bar_y, bar_x, bar_str)
            self.stdscr.attroff(blue_attr)

            msg_y = bar_y + 1
            if msg_y < height:
                msg_text = self.progress_message[:width - 4]
                msg_x = max(0, (width - len(msg_text)) // 2)
                self.stdscr.addstr(msg_y, msg_x, msg_text, curses.A_DIM)

        self.stdscr.refresh()

    def render(self):
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        if height < 10 or width < 40:
            self.stdscr.addstr(0, 0, "Terminal demasiado pequeña.", curses.A_REVERSE)
            self.stdscr.refresh()
            return
        header = " Bookish TUI"
        self.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        self.stdscr.addstr(0, 0, header + " " * max(0, width - len(header) - 1))
        self.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
        self.stdscr.addstr(2, 2, "Registro de Ejecución en Tiempo Real:", curses.A_BOLD)
        self.stdscr.addstr(3, 2, "─" * max(10, width - 4))
        max_visible_logs = max(1, height - 7)
        visible_logs = self.logs[-max_visible_logs:]
        for idx, (t, msg, cat) in enumerate(visible_logs):
            y = 4 + idx
            if y >= height - 2:
                break
            color_pair = curses.color_pair(5)
            prefix = "[INFO]"
            if cat == "success":
                color_pair = curses.color_pair(2) | curses.A_BOLD
                prefix = "[  OK  ]"
            elif cat == "warn":
                color_pair = curses.color_pair(3) | curses.A_BOLD
                prefix = "[ WARN ]"
            elif cat == "error":
                color_pair = curses.color_pair(4) | curses.A_BOLD
                prefix = "[ERROR ]"
            elif cat == "step":
                color_pair = curses.color_pair(1) | curses.A_BOLD
                prefix = "[PASO ]"
            self.stdscr.attron(color_pair)
            self.stdscr.addstr(y, 2, f"{t} {prefix} ")
            self.stdscr.attroff(color_pair)
            max_text_w = max(10, width - 20)
            self.stdscr.addstr(y, 18, msg[:max_text_w])
        footer_y = height - 1
        self.stdscr.addstr(footer_y, 2, "Procesando tareas universitarias... Espere por favor.", curses.A_DIM)
        self.stdscr.refresh()

def ensure_directories():
    os.makedirs(os.path.join(PROJECT_ROOT, "data"), exist_ok=True)
    os.makedirs(DRAFTS_DIR, exist_ok=True)
    os.makedirs(PDFS_DIR, exist_ok=True)
    os.makedirs(PRESENTATIONS_DIR, exist_ok=True)
    os.makedirs(HANDOFF_DIR, exist_ok=True)

def _detect_project_path(handoff_content):
    """
    Detects if the user specified an existing project directory in the handoff.
    Scans for absolute paths or home paths (~/...) and verifies if they exist.
    Avoids detecting Bookish's internal directories.
    Returns the absolute path to the directory, or None.
    """
    matches = re.findall(r'((?:~|/)(?:[a-zA-Z0-9_\-\.]+/)*[a-zA-Z0-9_\-\.]+)', handoff_content)
    for cand in matches:
        clean = cand.rstrip(',.:;\'"()[]{}')
        expanded = os.path.expanduser(clean)
        # Avoid matching Bookish repo itself or its subdirectories
        if expanded == PROJECT_ROOT or expanded.startswith(os.path.join(PROJECT_ROOT, "data")):
            continue
        if os.path.isdir(expanded):
            return os.path.abspath(expanded)
        elif os.path.isfile(expanded):
            return os.path.dirname(os.path.abspath(expanded))
    return None


def _detect_route_from_handoff(handoff_content):
    """
    Detects the target project route specified by the user in the handoff file.
    First checks the dedicated line: '- **Ruta del Proyecto:** <path>'.
    Falls back to any detected absolute/home path, or PROJECT_ROOT.
    """
    # 1. Search for the explicit route line
    match = re.search(
        r'-\s*\*\*Ruta(?: del Proyecto)?(?:\s*/?\s*Workspace)?:\*\*\s*(.+)',
        handoff_content,
        re.IGNORECASE,
    )
    if match:
        raw_val = match.group(1).strip()
        clean_val = raw_val.strip('`"\'[]()').strip()
        if clean_val and not clean_val.startswith("<") and not clean_val.startswith("["):
            expanded = os.path.expanduser(clean_val)
            if os.path.isdir(expanded):
                return os.path.abspath(expanded)
            elif os.path.isfile(expanded):
                return os.path.dirname(os.path.abspath(expanded))
            elif clean_val.startswith("/") or clean_val.startswith("~"):
                try:
                    os.makedirs(expanded, exist_ok=True)
                except OSError:
                    pass
                return os.path.abspath(expanded)

    # 2. Fallback to generic project path detection
    detected = _detect_project_path(handoff_content)
    if detected:
        return detected

    # 3. Default to PROJECT_ROOT
    return PROJECT_ROOT


def create_handoff_file(item):
    title = item.get("title", "Sin Título")
    course_code = item.get("course_code", "")
    due_date = item.get("due_date", "Sin fecha límite")
    description = item.get("description", "")
    student_name = item.get("student_name", STUDENT_NAME)
    student_enrolment = item.get("student_enrolment") or item.get("student_enrrolment") or STUDENT_ENROLMENT
    additional_info = item.get("additional_info", "")
    safe_title = sanitize_filename(title)
    output_draft = os.path.join(DRAFTS_DIR, f"{safe_title}.md")
    format_rules = ""
    if os.path.exists(CONVERTER_FORMAT_FILE):
        with open(CONVERTER_FORMAT_FILE, "r", encoding="utf-8") as f:
            format_rules = f.read()
    additional_section = ""
    if additional_info:
        additional_section = f"## Contexto / Instrucciones Adicionales del Estudiante\n\n{additional_info}\n\n---\n\n"
    handoff_content = (
        f"# Contexto de Asignación — Handoff para Agente IA\n\n"
        f"> [!TIP]\n"
        f"> **INSTRUCCIONES DE AGENT HANDOFF (OPENCODE / TMUX)**:\n"
        f"> 1. En la línea `- **Ruta del Proyecto:**` (abajo en Metadatos), escribe la ruta del proyecto\n"
        f">    donde deseas que se abra OpenCode (ej: `/home/thegxnster/py/miniProjects/ruleta`).\n"
        f">    Si la dejas vacía, se abrirá en la carpeta de este repositorio.\n"
        f"> 2. Modifica o agrega las instrucciones necesarias en este archivo.\n"
        f"> 3. Al guardar y cerrar con `:x` o `:wq`:\n"
        f">    - Todo este archivo se COPIARÁ A TU PORTAPAPELES automáticamente.\n"
        f">    - Se abrirá un nuevo pane de tmux en la ruta especificada ejecutando OpenCode.\n"
        f">    - Solo tendrás que pegar el contenido con Ctrl+V y empezar a programar.\n\n"
        f"---\n\n"
        f"## Metadatos & Configuración\n"
        f"- **Asignatura:** {course_code}\n"
        f"- **Tarea:** {title}\n"
        f"- **Estudiante:** {student_name}\n"
        f"- **Matrícula:** {student_enrolment}\n"
        f"- **Fecha Límite:** {due_date}\n"
        f"- **Ruta del Proyecto:** \n\n"
        f"---\n\n"
        f"## Instrucciones de Moodle\n\n"
        f"{description}\n\n"
        f"---\n\n"
        f"{additional_section}"
        f"## Instrucciones para el Agente\n\n"
        f"[Escribe o modifica aquí lo que quieres que haga el agente.]\n\n"
        f"---\n\n"
        f"## Reglas de Formato (CONVERTER_FORMAT.md - Solo si la entrega es un documento PDF)\n\n"
        f"{format_rules}\n"
    )
    handoff_path = os.path.join(HANDOFF_DIR, f"{safe_title}.md")
    with open(handoff_path, "w", encoding="utf-8") as f:
        f.write(handoff_content)
    return handoff_path, output_draft


def handle_agent_handoff(stdscr, handoff_path, output_draft, title):
    curses.endwin()

    # Step 1: Open nvim for editing
    print(f"\n{'=' * 60}")
    print(f"  Tarea: {title}")
    print(f"  Abriendo contexto en nvim para edición...")
    print(f"  NOTA: Especifica la ruta en la línea:")
    print(f"        - **Ruta del Proyecto:** /tu/ruta/aqui")
    print(f"  Al salir (:x / :wq), el handoff se copiará a tu portapapeles")
    print(f"  y se abrirá OpenCode en un nuevo pane de tmux.")
    print(f"{'=' * 60}\n")

    editor = "nvim"
    try:
        subprocess.run([editor, handoff_path])
    except FileNotFoundError:
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vim"
        subprocess.run([editor, handoff_path])

    # Step 2: Read edited handoff content
    content = ""
    if os.path.exists(handoff_path):
        with open(handoff_path, "r", encoding="utf-8") as f:
            content = f.read()

    # Step 3: Copy entire handoff to clipboard
    copied = copy_to_clipboard(content)

    # Step 4: Detect route from the specific line
    target_route = _detect_route_from_handoff(content)

    # Step 5: Open opencode on a new tmux pane
    opencode_bin = shutil.which("opencode") or "opencode"
    is_in_tmux = bool(os.environ.get("TMUX"))

    print(f"\n{'=' * 60}")
    print(f"  Tarea: {title}")
    print(f"  Ruta detectada: {target_route}")
    if copied:
        print(f"  ✓ Handoff copiado exitosamente al portapapeles!")
    else:
        print(f"  ! Aviso: No se detectó herramienta de portapapeles (clip.exe/xclip).")

    if is_in_tmux:
        # Split window into a new pane in the target directory and run opencode
        split_cmd = ["tmux", "split-window", "-c", target_route, f"{opencode_bin}; exec bash"]
        split_res = subprocess.run(split_cmd)
        if split_res.returncode == 0:
            print(f"  ✓ OpenCode abierto en nuevo pane de tmux en:")
            print(f"    {target_route}")
            print(f"  → Pega el portapapeles (Ctrl+V) en OpenCode y maneja la sesión.")
        else:
            print(f"  ! Error abriendo pane en tmux. Abriendo en proceso actual...")
            subprocess.run([opencode_bin], cwd=target_route)
    else:
        if shutil.which("tmux"):
            safe_title = sanitize_filename(title)
            session_name = f"opencode_{safe_title}"
            subprocess.run([
                "tmux", "new-session", "-d", "-s", session_name, "-c", target_route,
                f"{opencode_bin}; exec bash"
            ])
            print(f"  ✓ OpenCode iniciado en sesión tmux: {session_name}")
            print(f"  → Conéctate con: tmux attach -t {session_name}")
            print(f"  → Pega el portapapeles (Ctrl+V) y maneja la sesión.")
        else:
            print(f"  (No estás en tmux) Abriendo OpenCode en {target_route}...")
            try:
                subprocess.run([opencode_bin], cwd=target_route)
            except Exception as e:
                print(f"  Error ejecutando opencode: {e}")

    print(f"{'=' * 60}\n")
    try:
        input("Presiona Enter para continuar en Bookish...")
    except (EOFError, KeyboardInterrupt):
        pass

    stdscr.refresh()


# Backwards compatibility alias
launch_agent = handle_agent_handoff


def find_assignment_pdf(assignment):
    """
    Looks for the generated PDF file for a given assignment item.
    Checks explicit paths, DEFAULT_OUTPUT_DIR, and PDFS_DIR with case-insensitivity.
    Returns the absolute path if found, or None.
    """
    # 1. Check if assignment dictionary already has an explicit valid pdf_path
    explicit_path = assignment.get("pdf_path")
    if explicit_path and os.path.isfile(explicit_path) and os.path.getsize(explicit_path) > 0:
        return os.path.abspath(explicit_path)

    title = assignment.get("title", "")
    if not title:
        return None
    safe_title = sanitize_filename(title).lower()

    # 2. Check by filename in output directories
    for search_dir in (DEFAULT_OUTPUT_DIR, PDFS_DIR):
        if not os.path.isdir(search_dir):
            continue
        direct_pdf = os.path.join(search_dir, f"{safe_title}.pdf")
        if os.path.isfile(direct_pdf) and os.path.getsize(direct_pdf) > 0:
            return direct_pdf

        for fname in os.listdir(search_dir):
            if fname.lower().endswith(".pdf"):
                base = os.path.splitext(fname)[0].lower()
                if base == safe_title:
                    full_path = os.path.join(search_dir, fname)
                    if os.path.getsize(full_path) > 0:
                        return full_path
    return None


def remove_assignment_from_cache(assignment_url_or_title):
    """
    Removes an assignment from ASSIGNMENTS_FILE by url or title.
    """
    if not os.path.exists(ASSIGNMENTS_FILE):
        return
    try:
        with open(ASSIGNMENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            target = str(assignment_url_or_title).strip()
            new_data = [
                item for item in data
                if item.get("url", "").strip() != target
                and item.get("title", "").strip().lower() != target.lower()
            ]
            with open(ASSIGNMENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(new_data, f, indent=2, ensure_ascii=False)
            log.info(f"Removida tarea '{assignment_url_or_title}' de {ASSIGNMENTS_FILE}")
    except Exception as e:
        log.warning(f"Error updating assignments file after removal: {e}")


def _perform_upload(stdscr, logger, entry, items_list):
    """
    Helper to upload a single assignment file to Moodle, updating logs and cache.
    """
    title = entry["title"]
    height, width = stdscr.getmaxyx()
    stdscr.addstr(height - 4, 2, " " * max(10, width - 4))
    stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
    stdscr.addstr(height - 4, 2, f"Subiendo '{title[:max(10, width - 35)]}' a Moodle... Espere...")
    stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)
    stdscr.refresh()

    logger.log(f"Subiendo a Moodle: '{title}'...", "step")
    success, msg = upload_assignment_submission(entry["url"], entry["pdf_path"])
    if success:
        logger.log(f"✓ {title}: {msg}", "success")
        remove_assignment_from_cache(entry["url"])
        if entry in items_list:
            items_list.remove(entry)
        time.sleep(1)
        return True
    else:
        logger.log(f"✗ Error al subir '{title}': {msg}", "error")
        time.sleep(2)
        return False


def open_upload_menu(stdscr, logger):
    """
    Interactive curses menu for selecting and uploading completed assignments to Moodle.
    Allows:
    - [Up/Down / j/k] Navigate tasks
    - [1-9] Select directly by number
    - [Enter / Space] Upload selected task
    - [T] Upload ALL tasks with available PDF
    - [C / Esc / Q] Return to final screen
    """
    if not os.path.exists(ASSIGNMENTS_FILE):
        logger.log("No se encontró archivo de tareas para subir.", "warn")
        return

    try:
        with open(ASSIGNMENTS_FILE, "r", encoding="utf-8") as f:
            raw_assignments = json.load(f)
    except Exception as e:
        logger.log(f"Error leyendo asignaciones: {e}", "error")
        return

    if not raw_assignments:
        logger.log("No hay tareas pendientes en caché.", "info")
        return

    items_with_pdf = []
    for item in raw_assignments:
        if is_assignment_overdue(item.get("due_date", "")):
            continue
        pdf_path = find_assignment_pdf(item)
        items_with_pdf.append({
            "item": item,
            "title": item.get("title", "Sin Título"),
            "url": item.get("url", ""),
            "course_code": item.get("course_code", ""),
            "pdf_path": pdf_path,
            "has_pdf": pdf_path is not None,
        })

    selected_idx = 0
    status_msg = ""
    status_cat = "info"
    curses.curs_set(0)

    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        if height < 12 or width < 50:
            stdscr.addstr(0, 0, "Terminal demasiado pequeña.", curses.A_REVERSE)
            stdscr.addstr(1, 0, "Presione [C] para volver.")
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in [ord('c'), ord('C'), ord('q'), ord('Q'), 27]:
                break
            continue

        # Header
        header = " Bookish TUI | Subir Entregas a Moodle "
        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(0, 0, header + " " * max(0, width - len(header) - 1))
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        # Instructions
        stdscr.addstr(2, 2, "Seleccione la tarea que desea subir a Moodle:", curses.A_BOLD)
        stdscr.addstr(3, 2, "─" * max(10, width - 4))

        max_visible = max(1, height - 9)
        scroll_offset = 0
        if selected_idx >= max_visible:
            scroll_offset = selected_idx - max_visible + 1

        for i in range(max_visible):
            idx = scroll_offset + i
            if idx >= len(items_with_pdf):
                break
            entry = items_with_pdf[idx]
            y = 4 + i
            is_selected = (idx == selected_idx)

            num_str = f"[{idx + 1}] " if idx < 9 else f"[{idx + 1}]"
            prefix = " > " if is_selected else "   "
            course = f"[{entry['course_code']}] " if entry['course_code'] else ""
            title_text = f"{course}{entry['title']}"

            badge_len = 16
            max_title_len = max(10, width - 20 - badge_len)
            truncated_title = title_text[:max_title_len]

            attr = curses.A_REVERSE if is_selected else curses.A_NORMAL
            stdscr.attron(attr)
            stdscr.addstr(y, 2, f"{prefix}{num_str} {truncated_title}")
            stdscr.attroff(attr)

            badge_x = min(width - badge_len - 2, 8 + len(truncated_title) + 2)
            if entry["has_pdf"]:
                stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
                stdscr.addstr(y, badge_x, "[✓ PDF listo]")
                stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)
            else:
                stdscr.attron(curses.color_pair(3))
                stdscr.addstr(y, badge_x, "[✗ Sin PDF]")
                stdscr.attroff(curses.color_pair(3))

        # Status message line
        if status_msg:
            status_y = height - 4
            pair = curses.color_pair(2) if status_cat == "success" else (curses.color_pair(4) if status_cat == "error" else curses.color_pair(3))
            stdscr.attron(pair | curses.A_BOLD)
            stdscr.addstr(status_y, 2, status_msg[:max(10, width - 4)])
            stdscr.attroff(pair | curses.A_BOLD)

        # Footer
        sep_y = height - 3
        stdscr.addstr(sep_y, 2, "─" * max(10, width - 4))
        footer_y = height - 2
        stdscr.addstr(footer_y, 2, "[")
        stdscr.addstr("Enter", curses.color_pair(3) | curses.A_BOLD)
        stdscr.addstr("] Subir Seleccionada  [")
        stdscr.addstr("T", curses.color_pair(3) | curses.A_BOLD)
        stdscr.addstr("] Subir TODAS  [")
        stdscr.addstr("C", curses.color_pair(3) | curses.A_BOLD)
        stdscr.addstr("] Cancelar / Volver")

        hint_y = height - 1
        stdscr.addstr(hint_y, 2, "Navegue con ↑/↓ o teclas 1-9. Presione C o Q para regresar.", curses.A_DIM)

        stdscr.refresh()
        ch = stdscr.getch()

        if ch in [ord('c'), ord('C'), ord('q'), ord('Q'), 27]:
            break
        elif ch in [curses.KEY_UP, ord('k')]:
            if selected_idx > 0:
                selected_idx -= 1
        elif ch in [curses.KEY_DOWN, ord('j')]:
            if selected_idx < len(items_with_pdf) - 1:
                selected_idx += 1
        elif ord('1') <= ch <= ord('9'):
            target_idx = ch - ord('1')
            if target_idx < len(items_with_pdf):
                selected_idx = target_idx
                entry = items_with_pdf[selected_idx]
                if not entry["has_pdf"]:
                    status_msg = f"'{entry['title'][:35]}' no tiene archivo PDF generado aún."
                    status_cat = "warn"
                else:
                    _perform_upload(stdscr, logger, entry, items_with_pdf)
                    if not items_with_pdf:
                        break
                    selected_idx = min(selected_idx, len(items_with_pdf) - 1)
        elif ch in [10, 13, ord(' ')]:
            if 0 <= selected_idx < len(items_with_pdf):
                entry = items_with_pdf[selected_idx]
                if not entry["has_pdf"]:
                    status_msg = f"'{entry['title'][:35]}' no tiene archivo PDF generado aún."
                    status_cat = "warn"
                else:
                    _perform_upload(stdscr, logger, entry, items_with_pdf)
                    if not items_with_pdf:
                        break
                    selected_idx = min(selected_idx, len(items_with_pdf) - 1)
        elif ch in [ord('t'), ord('T')]:
            ready_entries = [e for e in items_with_pdf if e["has_pdf"]]
            if not ready_entries:
                status_msg = "No hay tareas con archivo PDF generado para subir."
                status_cat = "warn"
            else:
                total_ready = len(ready_entries)
                for i_upload, entry in enumerate(ready_entries, 1):
                    title = entry["title"]
                    stdscr.addstr(height - 4, 2, " " * max(10, width - 4))
                    stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
                    stdscr.addstr(height - 4, 2, f"Subiendo [{i_upload}/{total_ready}]: {title[:max(10, width - 30)]}...")
                    stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)
                    stdscr.refresh()

                    logger.log(f"Subiendo a Moodle [{i_upload}/{total_ready}]: '{title}'...", "step")
                    success, msg = upload_assignment_submission(entry["url"], entry["pdf_path"])
                    if success:
                        logger.log(f"✓ {title}: {msg}", "success")
                        remove_assignment_from_cache(entry["url"])
                        if entry in items_with_pdf:
                            items_with_pdf.remove(entry)
                    else:
                        logger.log(f"✗ Error al subir '{title}': {msg}", "error")

                logger.log("Subida por lote completada.", "success")
                time.sleep(1)
                break


def handle_final_screen(stdscr, logger):
    """
    Renders the final completion screen with options:
    [U] Subir Tareas  [V] Volver al Cuestionario  [Q] Salir
    Returns:
    - 'volver' when user wants to return to the questionnaire from the first cached task
    - 'quit' when user wants to exit
    """
    curses.curs_set(0)
    while True:
        logger.render()
        height, width = stdscr.getmaxyx()
        footer_y = height - 1

        stdscr.addstr(footer_y, 0, " " * (width - 1))
        stdscr.addstr(footer_y, 2, "[")
        stdscr.addstr("U", curses.color_pair(3) | curses.A_BOLD)
        stdscr.addstr("] Subir Tareas  [")
        stdscr.addstr("V", curses.color_pair(3) | curses.A_BOLD)
        stdscr.addstr("] Volver al Cuestionario  [")
        stdscr.addstr("Q", curses.color_pair(3) | curses.A_BOLD)
        stdscr.addstr("] Salir")
        stdscr.refresh()

        ch = stdscr.getch()
        if ch in [ord('q'), ord('Q'), 27]:
            return "quit"
        elif ch in [ord('v'), ord('V')]:
            return "volver"
        elif ch in [ord('u'), ord('U')]:
            open_upload_menu(stdscr, logger)

def run_bookish_pipeline(stdscr, force_refresh: bool = False):
    logger = BookishLogger(stdscr)
    ensure_directories()
    logger.set_progress(10, "Iniciando pipeline de Bookish...")
    time.sleep(0.2)
    
    # Step 1: Moodle Login (only if session missing or force_refresh)
    username = os.environ.get("BOOKISH_USERNAME")
    password = os.environ.get("BOOKISH_PASS")
    session_exists = os.path.exists(STATE_FILE) and os.path.getsize(STATE_FILE) > 0

    if not session_exists and username and password:
        logger.set_progress(25, f"Iniciando sesión en Moodle como {username}...")
        try:
            login_and_save_session(username, password)
            logger.set_progress(40, "Sesión de Moodle guardada exitosamente.")
            time.sleep(0.2)
        except Exception as e:
            logger.log(f"Error al iniciar sesión en Moodle: {e}", "error")
            time.sleep(3)
    elif session_exists:
        logger.set_progress(35, "Sesión de Moodle activa detectada.")
        time.sleep(0.2)
    else:
        logger.set_progress(35, "Omitiendo login automático.")
        time.sleep(0.2)
        
    # Step 2: Scraping (Incremental Differential Sync)
    sync_desc = "Sincronización forzada completa..." if force_refresh else "Sincronizando tareas y calendario..."
    logger.set_progress(50, sync_desc)
    try:
        total, reused, scraped = load_session_and_scrape(force_refresh=force_refresh)
        logger.set_progress(85, f"Scraping completado: {reused} en caché, {scraped} nuevas.")
        time.sleep(0.3)
    except Exception as e:
        if "expired" in str(e).lower() and username and password:
            logger.set_progress(60, "Sesión expirada. Re-autenticando en Moodle...")
            try:
                login_and_save_session(username, password)
                total, reused, scraped = load_session_and_scrape(force_refresh=force_refresh)
                logger.set_progress(85, f"Scraping completado tras login: {reused} en caché, {scraped} nuevas.")
                time.sleep(0.3)
            except Exception as retry_err:
                logger.log(f"Error en re-autenticación: {retry_err}", "error")
                time.sleep(3)
        else:
            logger.log(f"Advertencia en scraping: {e}", "warn")
            time.sleep(1)

    logger.set_progress(100, "Cargando cuestionario interactivo...")
    time.sleep(0.4)
    logger.show_splash = False
        
    while True:
        if not os.path.exists(ASSIGNMENTS_FILE):
            logger.log(f"No se encontró el archivo {ASSIGNMENTS_FILE}.", "error")
            time.sleep(2)
            return

        try:
            with open(ASSIGNMENTS_FILE, "r", encoding="utf-8") as f:
                assignments = json.load(f)
        except Exception as e:
            logger.log(f"Error al leer asignaciones: {e}", "error")
            time.sleep(2)
            return

        if not assignments:
            logger.log("No hay asignaciones pendientes en caché o todas han sido enviadas.", "success")
            final_action = handle_final_screen(stdscr, logger)
            if final_action == "volver":
                logger.log("No hay más tareas en caché para mostrar.", "warn")
                time.sleep(1)
                continue
            else:
                break

        # Step 3: TUI Questionnaire
        logger.log("[3/6] Iniciando cuestionario interactivo...", "step")
        time.sleep(0.5)
        pending_items = []
        for item in assignments:
            title = item.get("title", "")
            desc = item.get("description", "").strip()
            due_date = item.get("due_date", "")
            if not desc or is_assignment_overdue(due_date):
                continue
            safe_title = sanitize_filename(title)
            md_file = os.path.join(DRAFTS_DIR, f"{safe_title}.md")
            png_file = os.path.join(PRESENTATIONS_DIR, f"{safe_title}.png")
            item["md_file"] = md_file
            item["png_file"] = png_file
            pending_items.append(item)

        if not pending_items:
            logger.log("Todas las asignaciones ya tienen borrador o presentación generada.", "success")
            final_action = handle_final_screen(stdscr, logger)
            if final_action == "volver":
                continue
            else:
                break

        approved_drafts = []
        approved_presentations = []
        approved_markdown_only = []
        agent_handoffs = []
        session_generated_mds = []
        total_pending = len(pending_items)
        user_cancelled = False

        for idx, item in enumerate(pending_items, 1):
            action, additional_info = curses_prompt_assignment(stdscr, item, idx, total_pending)
            if action == "quit":
                user_cancelled = True
                break
            elif action == "upload":
                title = item.get("title", "Sin Título")
                pdf_path = find_assignment_pdf(item)
                if not pdf_path:
                    logger.log(f"No se encontró PDF para '{title}'. Genera el borrador o conviértelo primero.", "error")
                    time.sleep(2)
                    continue
                logger.log(f"Subiendo '{title}' a Moodle...", "step")
                success, msg = upload_assignment_submission(item.get("url"), pdf_path)
                if success:
                    logger.log(f"✓ {title}: {msg}", "success")
                    remove_assignment_from_cache(item.get("url"))
                    time.sleep(1.5)
                else:
                    logger.log(f"✗ Fallo al subir '{title}': {msg}", "error")
                    time.sleep(2.5)
            elif action == "yes":
                item["additional_info"] = additional_info
                approved_drafts.append(item)
            elif action == "markdown_only":
                item["additional_info"] = additional_info
                approved_markdown_only.append(item)
            elif action == "presentation":
                approved_presentations.append(item)
            elif action in ("agent_handoff", "agent_agy", "agent_opencode"):
                item["additional_info"] = additional_info
                title = item.get("title", "Sin Título")
                logger.log(f"Iniciando Agent Handoff para '{title}'...", "info")
                handoff_path, output_draft = create_handoff_file(item)
                handle_agent_handoff(stdscr, handoff_path, output_draft, title)
                agent_handoffs.append(item)
                if os.path.exists(output_draft):
                    session_generated_mds.append(output_draft)

        if user_cancelled:
            logger.log("Cuestionario interrumpido por el usuario.", "warn")
            final_action = handle_final_screen(stdscr, logger)
            if final_action == "volver":
                logger.log("Regresando a la primera tarea en caché...", "step")
                continue
            else:
                break

        summary_parts = []
        if approved_drafts:
            summary_parts.append(f"{len(approved_drafts)} borradores (PDF)")
        if approved_markdown_only:
            summary_parts.append(f"{len(approved_markdown_only)} solo-Markdown")
        if approved_presentations:
            summary_parts.append(f"{len(approved_presentations)} presentaciones")
        if agent_handoffs:
            summary_parts.append(f"{len(agent_handoffs)} enviadas a Agent Handoff")

        logger.log(f"Cuestionario completado: {', '.join(summary_parts) if summary_parts else 'ninguna tarea seleccionada'}.", "success")
        time.sleep(1)

        # Step 4: Presentations
        if approved_presentations:
            logger.log(f"[4/6] Renderizando {len(approved_presentations)} presentación(es) PNG...", "step")
            for item in approved_presentations:
                title = item.get("title", "Sin Título")
                logger.log(f"Renderizando hoja de presentación para '{title}'...", "info")
                try:
                    png_out = render_presentation_png(item)
                    logger.log(f"Guardada presentación PNG: {os.path.basename(png_out)}", "success")
                except Exception as e:
                    logger.log(f"Error renderizando presentación para '{title}': {e}", "error")

        # Step 5: AI Drafts
        all_ai_items = approved_drafts + approved_markdown_only
        if all_ai_items:
            logger.log(f"[5/6] Generando {len(all_ai_items)} borrador(es) con IA...", "step")
            gemini_key = os.environ.get("GEMINI_API_KEY")
            if not gemini_key:
                logger.log("Error: GEMINI_API_KEY no está configurada en el entorno.", "error")
                time.sleep(2)
            else:
                try:
                    import google.genai as _genai
                    client = _genai.Client()
                    for item in all_ai_items:
                        is_pdf_target = item in approved_drafts
                        title = item.get("title", "Sin Título")
                        description = item.get("description", "")
                        course_code = item.get("course_code", "")
                        course_name = item.get("course_name", "")
                        due_date = item.get("due_date", "Sin fecha límite")
                        student_name = item.get("student_name", STUDENT_NAME)
                        student_enrolment = item.get("student_enrolment") or item.get("student_enrrolment") or STUDENT_ENROLMENT
                        additional_info = item.get("additional_info", "")
                        output_file = item["md_file"]
                        tag = "Borrador PDF" if is_pdf_target else "Solo Markdown"
                        logger.log(f"Generando {tag} para '{title}'...", "info")
                        try:
                            draft_content = generate_assignment_draft(
                                client, title, description, course_code, course_name, due_date,
                                additional_info="",
                                custom_prompt=additional_info
                            )
                            header = build_cover_page_html(
                                course_code=course_code,
                                title=title,
                                student_name=student_name,
                                student_enrolment=student_enrolment,
                                due_date=due_date,
                            )
                            with open(output_file, "w", encoding="utf-8") as f:
                                f.write(header + "\n\n" + draft_content)
                            logger.log(f"Guardado borrador Markdown ({tag}): {os.path.basename(output_file)}", "success")
                            if is_pdf_target:
                                session_generated_mds.append(output_file)
                        except Exception as e:
                            logger.log(f"Error al generar borrador para '{title}': {e}", "error")
                except ImportError:
                    logger.log("Error: google-genai no está instalado.", "error")
                    time.sleep(2)
                except Exception as e:
                    logger.log(f"Error inicializando cliente Gemini: {e}", "error")

        # Step 6: PDF Conversion
        if session_generated_mds:
            logger.log(f"[6/6] Convirtiendo {len(session_generated_mds)} borrador(es) de la sesión actual a PDF...", "step")
            for md_file in session_generated_mds:
                try:
                    convert_md_to_pdf(target=md_file)
                    logger.log(f"Guardado y abierto PDF: {os.path.basename(md_file).replace('.md', '.pdf')}", "success")
                except Exception as e:
                    logger.log(f"Error convirtiendo '{os.path.basename(md_file)}': {e}", "error")
        else:
            logger.log("[6/6] No hay borradores generados en esta sesión para convertir a PDF.", "info")

        logger.log("=========================================", "info")
        logger.log("  Proceso completado!", "success")
        logger.log(f"  Archivos en: {DEFAULT_OUTPUT_DIR}", "info")
        logger.log("=========================================", "info")

        final_action = handle_final_screen(stdscr, logger)
        if final_action == "volver":
            logger.log("Regresando a la primera tarea en caché...", "step")
            continue
        else:
            break

def main():
    force_refresh = False
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ('--version', '-v'):
            try:
                from bookish_pkg import __version__
                print(f"bookish {__version__}")
            except ImportError:
                print("bookish (version unknown)")
            return
        elif arg in ('--help', '-h'):
            print("Usage: bookish [options]")
            print("")
            print("Academic automation engine for UCE Moodle.")
            print("")
            print("Options:")
            print("  --refresh, -r, --sync  Force full re-scrape of all assignments from Moodle")
            print("  --version, -v          Show version and exit")
            print("  --help, -h             Show this help and exit")
            print("")
            print("Environment variables:")
            print("  BOOKISH_USERNAME      Moodle username for auto-login")
            print("  BOOKISH_PASS          Moodle password for auto-login")
            print("  GEMINI_API_KEY        Google Gemini API key for draft generation")
            print("  BOOKISH_OUTPUT_DIR    Custom output directory")
            return
        elif arg in ('--refresh', '-r', '--sync'):
            force_refresh = True

    try:
        curses.wrapper(lambda stdscr: run_bookish_pipeline(stdscr, force_refresh=force_refresh))
    except KeyboardInterrupt:
        print("\nEjecución cancelada por el usuario.", file=sys.stderr)
    except Exception as e:
        print(f"\nError durante la ejecución: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

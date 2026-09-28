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
    STUDENT_NAME, STUDENT_ENROLMENT,
)
from bookish_pkg.utils import sanitize_filename, build_cover_page_html, copy_to_clipboard
from bookish_pkg.scraper import login_and_save_session, load_session_and_scrape
from bookish_pkg.generator import curses_prompt_assignment, generate_assignment_draft
from bookish_pkg.converter import convert_md_to_pdf, render_presentation_png

log = logging.getLogger(__name__)

class BookishLogger:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.logs = []
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
        except Exception:
            pass

    def log(self, message, category="info"):
        timestamp = time.strftime("%H:%M:%S")
        self.logs.append((timestamp, message, category))
        log.info(f"[{category.upper()}] {message}")
        self.render()

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
    student_enrrolment = item.get("student_enrrolment", STUDENT_ENROLMENT)
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
        f"- **Matrícula:** {student_enrrolment}\n"
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

def run_bookish_pipeline(stdscr):
    logger = BookishLogger(stdscr)
    ensure_directories()
    logger.log("Iniciando pipeline de Bookish...", "step")
    
    # Step 1: Moodle Login
    username = os.environ.get("BOOKISH_USERNAME")
    password = os.environ.get("BOOKISH_PASS")
    if username and password:
        logger.log(f"[1/6] Credenciales detectadas para {username}. Iniciando sesión Moodle...", "step")
        try:
            login_and_save_session(username, password)
            logger.log("Sesión de Moodle guardada exitosamente.", "success")
        except Exception as e:
            logger.log(f"Error al iniciar sesión en Moodle: {e}", "error")
            time.sleep(2)
    else:
        logger.log("[1/6] Omitiendo login automático (BOOKISH_USERNAME no configurado).", "info")
        
    # Step 2: Scraping
    logger.log("[2/6] Extrayendo asignaciones pendientes de Moodle...", "step")
    try:
        load_session_and_scrape()
        logger.log("Scraping de asignaciones completado.", "success")
    except Exception as e:
        logger.log(f"Advertencia en scraping: {e}", "warn")
        
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
        logger.log("No hay asignaciones encontradas o todas han sido enviadas.", "success")
        time.sleep(2)
        return
        
    # Step 3: TUI Questionnaire
    logger.log("[3/6] Iniciando cuestionario interactivo...", "step")
    time.sleep(1)
    pending_items = []
    for item in assignments:
        title = item.get("title", "")
        desc = item.get("description", "").strip()
        if not desc:
            continue
        safe_title = sanitize_filename(title)
        md_file = os.path.join(DRAFTS_DIR, f"{safe_title}.md")
        png_file = os.path.join(PRESENTATIONS_DIR, f"{safe_title}.png")
        item["md_file"] = md_file
        item["png_file"] = png_file
        pending_items.append(item)
        
    if not pending_items:
        logger.log("Todas las asignaciones ya tienen borrador o presentación generada.", "success")
        time.sleep(2)
        return
        
    approved_drafts = []
    approved_presentations = []
    approved_markdown_only = []
    agent_handoffs = []
    session_generated_mds = []
    total_pending = len(pending_items)
    
    for idx, item in enumerate(pending_items, 1):
        action, additional_info = curses_prompt_assignment(stdscr, item, idx, total_pending)
        if action == "quit":
            logger.log("Operación cancelada por el usuario.", "warn")
            time.sleep(1)
            return
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
                    student_enrrolment = item.get("student_enrrolment", STUDENT_ENROLMENT)
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
                            student_enrolment=student_enrrolment,
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
    stdscr.addstr(stdscr.getmaxyx()[0] - 1, 2, "Presione cualquier tecla para cerrar...", curses.A_BOLD | curses.color_pair(2))
    stdscr.refresh()
    stdscr.getch()

def main():
    if len(sys.argv) > 1:
        if sys.argv[1] in ('--version', '-v'):
            try:
                from bookish_pkg import __version__
                print(f"bookish {__version__}")
            except ImportError:
                print("bookish (version unknown)")
            return
        elif sys.argv[1] in ('--help', '-h'):
            print("Usage: bookish [options]")
            print("")
            print("Academic automation engine for UCE Moodle.")
            print("")
            print("Options:")
            print("  --version, -v    Show version and exit")
            print("  --help, -h       Show this help and exit")
            print("")
            print("Environment variables:")
            print("  BOOKISH_USERNAME      Moodle username for auto-login")
            print("  BOOKISH_PASS          Moodle password for auto-login")
            print("  GEMINI_API_KEY        Google Gemini API key for draft generation")
            print("  BOOKISH_OUTPUT_DIR    Custom output directory (default: /mnt/c/Users/frank/Downloads/bookish)")
            return

    try:
        curses.wrapper(run_bookish_pipeline)
    except KeyboardInterrupt:
        print("\nEjecución cancelada por el usuario.", file=sys.stderr)
    except Exception as e:
        print(f"\nError durante la ejecución: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

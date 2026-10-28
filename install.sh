#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$SCRIPT_DIR"

# ANSI Color codes for friendly output
BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
CYAN="\033[36m"
RED="\033[31m"
RESET="\033[0m"

echo -e "${BOLD}${CYAN}=== Installing Bookish Academic Automation Engine ===${RESET}\n"

# -------------------------------------------------------------------
# 1. System Prerequisite Checks & Diagnostics
# -------------------------------------------------------------------
echo -e "${BOLD}[Step 1/5] Checking System Prerequisites & Dependencies...${RESET}"

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Error: Python 3 is required but not installed.${RESET}" >&2
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "  ✓ Python version: ${GREEN}$PYTHON_VERSION${RESET}"

# Check for Tesseract OCR binary
if command -v tesseract &>/dev/null; then
    echo -e "  ✓ Tesseract OCR binary: ${GREEN}Installed${RESET}"
else
    echo -e "  ! Tesseract OCR binary: ${YELLOW}Not found${RESET}"
    echo -e "    ${YELLOW}Note: OCR text extraction from scanned PDFs/images requires tesseract.${RESET}"
    echo -e "    ${YELLOW}To install on Ubuntu/Debian/WSL: sudo apt update && sudo apt install -y tesseract-ocr tesseract-ocr-spa${RESET}"
fi

# Check document viewer
if command -v wslview &>/dev/null; then
    echo -e "  ✓ Document viewer: ${GREEN}wslview (WSL)${RESET}"
elif command -v xdg-open &>/dev/null; then
    echo -e "  ✓ Document viewer: ${GREEN}xdg-open (Linux)${RESET}"
elif command -v open &>/dev/null; then
    echo -e "  ✓ Document viewer: ${GREEN}open (macOS)${RESET}"
else
    echo -e "  ! Document viewer: ${YELLOW}None detected (wslview/xdg-open/open). Generated files won't auto-open.${RESET}"
fi

# Check External AI Tools (OpenCode / tmux / clipboard)
echo -e "\n${BOLD}Checking Agent Handoff Tools (for option [H]):${RESET}"

if command -v tmux &>/dev/null; then
    echo -e "  ✓ tmux: ${GREEN}Detected${RESET}"
else
    echo -e "  - tmux: ${YELLOW}Not detected${RESET} (Recommended for automatic split-pane OpenCode execution)"
fi

if command -v opencode &>/dev/null; then
    echo -e "  ✓ OpenCode CLI: ${GREEN}Detected${RESET}"
else
    echo -e "  - OpenCode CLI: ${YELLOW}Not detected${RESET} (Agent handoff will look for 'opencode')"
fi

echo ""

# -------------------------------------------------------------------
# 2. Interactive Configuration Wizard
# -------------------------------------------------------------------
ENV_FILE="$SCRIPT_DIR/.env"

# Default configuration values
DEF_STUDENT_NAME="Estudiante Universitario"
DEF_STUDENT_ENROLMENT="2024-0000"

# Detect WSL Downloads directory or fallback to ~/Downloads/bookish
if [ -d "/mnt/c/Users" ]; then
    WIN_USER=$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r' || true)
    if [ -n "$WIN_USER" ] && [ -d "/mnt/c/Users/$WIN_USER/Downloads" ]; then
        DEF_OUTPUT_DIR="/mnt/c/Users/$WIN_USER/Downloads/bookish"
    else
        DEF_OUTPUT_DIR="$HOME/Downloads/bookish"
    fi
else
    DEF_OUTPUT_DIR="$HOME/Downloads/bookish"
fi

# Load existing values if .env already exists
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE" 2>/dev/null || true
    set +a
fi

STUDENT_NAME="${BOOKISH_STUDENT_NAME:-$DEF_STUDENT_NAME}"
STUDENT_ENROLMENT="${BOOKISH_STUDENT_ENROLMENT:-$DEF_STUDENT_ENROLMENT}"
OUTPUT_DIR="${BOOKISH_OUTPUT_DIR:-$DEF_OUTPUT_DIR}"
GEMINI_KEY="${GEMINI_API_KEY:-}"
MOODLE_USER="${BOOKISH_USERNAME:-}"
MOODLE_PASS="${BOOKISH_PASS:-}"

IS_INTERACTIVE=true
if [ "$1" = "--non-interactive" ] || [ "$1" = "-y" ] || [ ! -t 0 ]; then
    IS_INTERACTIVE=false
fi

if [ "$IS_INTERACTIVE" = true ]; then
    echo -e "${BOLD}[Step 2/5] Interactive Configuration Wizard...${RESET}"
    echo -e "Press [Enter] to accept default values shown in brackets.\n"

    read -rp "1. Student Name [$STUDENT_NAME]: " INPUT_NAME
    STUDENT_NAME="${INPUT_NAME:-$STUDENT_NAME}"

    read -rp "2. Student Enrolment ID / Matrícula [$STUDENT_ENROLMENT]: " INPUT_ENROL
    STUDENT_ENROLMENT="${INPUT_ENROL:-$STUDENT_ENROLMENT}"

    read -rp "3. Output Directory [$OUTPUT_DIR]: " INPUT_OUT
    OUTPUT_DIR="${INPUT_OUT:-$OUTPUT_DIR}"

    if [ -n "$GEMINI_KEY" ]; then
        READ_KEY_PROMPT="4. Gemini API Key [***** (configured)]: "
    else
        READ_KEY_PROMPT="4. Gemini API Key (optional): "
    fi
    read -rp "$READ_KEY_PROMPT" INPUT_GEMINI
    if [ -n "$INPUT_GEMINI" ]; then
        GEMINI_KEY="$INPUT_GEMINI"
    fi

    if [ -n "$MOODLE_USER" ]; then
        READ_USER_PROMPT="5. Moodle Username [$MOODLE_USER]: "
    else
        READ_USER_PROMPT="5. Moodle Username (optional): "
    fi
    read -rp "$READ_USER_PROMPT" INPUT_USER
    if [ -n "$INPUT_USER" ]; then
        MOODLE_USER="$INPUT_USER"
    fi

    if [ -n "$MOODLE_PASS" ]; then
        echo -n "6. Moodle Password [***** (configured)]: "
        read -rs INPUT_PASS
        echo ""
    else
        echo -n "6. Moodle Password (optional, hidden input): "
        read -rs INPUT_PASS
        echo ""
    fi
    if [ -n "$INPUT_PASS" ]; then
        MOODLE_PASS="$INPUT_PASS"
    fi
else
    echo -e "${BOLD}[Step 2/5] Running in Non-Interactive Mode (Using defaults / environment)...${RESET}"
fi

# Write updated variables to .env file
cat <<EOF > "$ENV_FILE"
# Bookish Configuration File
BOOKISH_STUDENT_NAME="$STUDENT_NAME"
BOOKISH_STUDENT_ENROLMENT="$STUDENT_ENROLMENT"
BOOKISH_OUTPUT_DIR="$OUTPUT_DIR"
GEMINI_API_KEY="$GEMINI_KEY"
BOOKISH_USERNAME="$MOODLE_USER"
BOOKISH_PASS="$MOODLE_PASS"
EOF

chmod 600 "$ENV_FILE"
echo -e "  ✓ Configuration saved to: ${GREEN}$ENV_FILE${RESET}\n"

# -------------------------------------------------------------------
# 3. Virtual Environment Setup
# -------------------------------------------------------------------
echo -e "${BOLD}[Step 3/5] Setting up Python Virtual Environment...${RESET}"
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "  Creating virtual environment in .venv..."
    python3 -m venv "$SCRIPT_DIR/.venv"
else
    echo "  Virtual environment .venv already exists."
fi

# -------------------------------------------------------------------
# 4. Install Python Dependencies
# -------------------------------------------------------------------
echo -e "${BOLD}[Step 4/5] Installing Python Dependencies & Playwright Chromium...${RESET}"
"$SCRIPT_DIR/.venv/bin/pip" install -q --upgrade pip
"$SCRIPT_DIR/.venv/bin/pip" install -q -e "$SCRIPT_DIR"
echo -e "  ✓ Installed Bookish package in editable mode"

echo "  Installing Playwright Chromium browser binary..."
"$SCRIPT_DIR/.venv/bin/playwright" install chromium
echo -e "  ✓ Playwright Chromium browser installed"

# -------------------------------------------------------------------
# 5. Executable Symlink & PATH Verification
# -------------------------------------------------------------------
echo -e "\n${BOLD}[Step 5/5] Setting up executable symlink...${RESET}"
chmod +x "$SCRIPT_DIR/bookish"

BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
ln -sf "$SCRIPT_DIR/bookish" "$BIN_DIR/bookish"
echo -e "  ✓ Symlinked executable to: ${GREEN}$BIN_DIR/bookish${RESET}"

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo -e "\n  ${YELLOW}NOTE: $BIN_DIR is not in your \$PATH.${RESET}"
    echo -e "  ${YELLOW}Add it to your environment by running:${RESET}"
    echo -e "    ${CYAN}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc${RESET}"
fi

echo -e "\n${BOLD}${GREEN}=== Installation Successful ===${RESET}"
echo -e "Configuration Summary:"
echo -e "  - Student: ${CYAN}$STUDENT_NAME ($STUDENT_ENROLMENT)${RESET}"
echo -e "  - Output Folder: ${CYAN}$OUTPUT_DIR${RESET}"
if [ -n "$GEMINI_KEY" ]; then
    echo -e "  - Gemini API Key: ${GREEN}Configured${RESET}"
else
    echo -e "  - Gemini API Key: ${YELLOW}Not set (can set in .env or environment)${RESET}"
fi
if [ -n "$MOODLE_USER" ]; then
    echo -e "  - Moodle User: ${GREEN}$MOODLE_USER${RESET}"
else
    echo -e "  - Moodle User: ${YELLOW}Not set (will prompt if needed)${RESET}"
fi
echo -e "\nYou can now run ${BOLD}bookish${RESET} from anywhere in your terminal."

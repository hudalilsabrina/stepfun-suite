#!/usr/bin/env bash
# ==============================================================================
# StepFun Suite Dependency Installer
# Sets up Python virtual environment, dependencies, and Chromium browser.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

echo "=== [1/4] Checking Python 3 Installation ==="
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 is not installed. Please install Python 3.10+ first."
    exit 1
fi
PYTHON_BIN="$(command -v python3)"
echo "Using: $(${PYTHON_BIN} --version) at ${PYTHON_BIN}"

echo "=== [2/4] Setting up Virtual Environment ==="
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating virtual environment at ${VENV_DIR}..."
    ${PYTHON_BIN} -m venv "${VENV_DIR}"
else
    echo "Virtual environment already exists at ${VENV_DIR}."
fi

VENV_PYTHON="${VENV_DIR}/bin/python"
VENV_PIP="${VENV_DIR}/bin/pip"

"${VENV_PIP}" install --upgrade pip

echo "=== [3/4] Installing Required Python Packages ==="
"${VENV_PIP}" install -r "${SCRIPT_DIR}/requirements.txt"

echo "=== [4/4] Installing Playwright Chromium & System Dependencies ==="
"${VENV_PYTHON}" -m playwright install chromium
if command -v apt-get &>/dev/null && [ "$(id -u)" -eq 0 ]; then
    echo "Installing system browser libraries via apt..."
    "${VENV_PYTHON}" -m playwright install-deps chromium 2>/dev/null || true
fi

echo ""
echo "=============================================================================="
echo "✓ Installation Complete!"
echo "Run with the venv python:"
echo "  ${VENV_PYTHON} main.py --help"
echo "Or activate the environment:"
echo "  source ${VENV_DIR}/bin/activate"
echo "  python main.py auto"
echo "=============================================================================="

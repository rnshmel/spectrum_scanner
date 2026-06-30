#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo ""
echo "================================================"
echo "spectrum_scanner and scan_viewer toolset"
echo "================================================"

# Get the absolute directory of where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
REQ_FILE="requirements.txt"
APPS_DIR="apps"

# Define the help function
print_help() {
    echo "Usage: ./run.sh [-v] <app_script>"
    echo ""
    echo "Options:"
    echo "  -h, --help    Show this help message and exit"
    echo "  -v            Enable verbose (debug) logging"
    echo ""
    echo "Available applications in '$APPS_DIR/':"
    if [ -d "$APPS_DIR" ]; then
        ls "$APPS_DIR"/*.py 2>/dev/null | xargs -n 1 basename | sed 's/^/  - /' || echo "  (No python apps found in $APPS_DIR)"
    else
        echo "  (No apps directory found)"
    fi
    echo ""
}

APP_NAME=""
PYTHON_ARGS=""

# Parse arguments
for arg in "$@"; do
    case $arg in
        -h|--help)
            print_help
            exit 0
            ;;
        -v)
            PYTHON_ARGS="$PYTHON_ARGS --verbose"
            ;;
        -*)
            echo "Error: Unknown option '$arg'"
            print_help
            exit 1
            ;;
        *)
            if [ -z "$APP_NAME" ]; then
                APP_NAME="$arg"
            else
                echo "Error: Multiple application scripts provided."
                print_help
                exit 1
            fi
            ;;
    esac
done

# Require an app name
if [ -z "$APP_NAME" ]; then
    echo "Error: No application script specified."
    echo ""
    print_help
    exit 1
fi

TARGET_PATH="$APPS_DIR/$APP_NAME"

# Handle case where user omits .py extension
if [ ! -f "$TARGET_PATH" ] && [ -f "${TARGET_PATH}.py" ]; then
    TARGET_PATH="${TARGET_PATH}.py"
    APP_NAME="${APP_NAME}.py"
fi

if [ ! -f "$TARGET_PATH" ]; then
    echo "Error: Application script '$TARGET_PATH' not found."
    echo ""
    print_help
    exit 1
fi

# Select Python interpreter
PREFERRED_VERSIONS=("python3.11" "python3.10" "python3.9" "python3.8" "python3")
PYTHON_CMD=""

for ver in "${PREFERRED_VERSIONS[@]}"; do
    if command -v "$ver" &> /dev/null; then
        PYTHON_CMD="$ver"
        echo "--- Selected Python interpreter: $PYTHON_CMD ---"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "Error: Could not find a valid Python 3 interpreter."
    exit 1
fi

# Check if the virtual environment exists and create it if it doesn't
if [ ! -d "$VENV_DIR" ]; then
    echo "--- Checking if the 'venv' module is available ---"
    if ! "$PYTHON_CMD" -c "import venv" &> /dev/null; then
        echo "Error: The 'venv' module is not available for $PYTHON_CMD."
        echo "On Debian/Ubuntu systems, you might need to install it manually:"
        echo "  sudo apt install ${PYTHON_CMD}-venv"
        exit 1
    fi

    echo "--- Creating new virtual environment ($VENV_DIR) ---"
    # If the creation fails we need to clean up the partially created directory
    if ! "$PYTHON_CMD" -m venv "$VENV_DIR"; then
        echo "Error: Failed to create venv using $PYTHON_CMD. Cleaning up."
        rm -rf "$VENV_DIR"
        exit 1
    fi

    source "$VENV_DIR/bin/activate"
    
    echo "--- Upgrading pip and build tools ---"
    if ! pip install --upgrade pip setuptools wheel; then
        echo "Error: Pip upgrade failed. Cleaning up."
        deactivate
        rm -rf "$VENV_DIR"
        exit 1
    fi
    
    if [ -f "$REQ_FILE" ]; then
        echo "--- Installing dependencies from $REQ_FILE ---"
        if ! pip install -r "$REQ_FILE"; then
            echo "Error: Dependency installation failed. Cleaning up."
            deactivate
            rm -rf "$VENV_DIR"
            exit 1
        fi
    else
        echo "Warning: $REQ_FILE not found in $SCRIPT_DIR"
    fi
else
    echo "Activating existing virtual environment (offline mode)"
    source "$VENV_DIR/bin/activate"
fi

# Set PYTHONPATH specifically for spectrum_scanner
export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"

# Check if hackrf_sweep is available on the system
# TODO: add additional SDR checks
if ! command -v hackrf_sweep &> /dev/null; then
    echo -e "\nWARNING: 'hackrf_sweep' utility not found."
    echo -e "HackRF radio will not be a usable SDR for scanning."
    echo ""
fi

# Launch the selected application
echo "--- Launching application: $APP_NAME $PYTHON_ARGS ---"
python "$TARGET_PATH" $PYTHON_ARGS

# Deactivate the virtual environment when the GUI is closed
deactivate
echo "Application closed safely."

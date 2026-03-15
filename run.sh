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

# Define the help function
print_help() {
    echo "Usage: ./run.sh [-v] <app_script.py>"
    echo ""
    echo "Options:"
    echo "  -h, --help    Show this help message and exit"
    echo "  -v            Enable verbose (debug) logging"
    echo ""
    echo "Available applications in 'apps/':"
    if [ -d "apps" ]; then
        for f in apps/*.py; do
            [ -e "$f" ] && echo "  - $(basename "$f")"
        done
    else
        echo "  (No apps found)"
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

APP_PATH="apps/$APP_NAME"

if [ ! -f "$APP_PATH" ]; then
    echo "Error: Application script '$APP_PATH' not found."
    echo ""
    print_help
    exit 1
fi

# Check if the virtual environment exists, create it if it doesn't
if [ ! -d ".venv" ]; then
    echo "Creating new Python virtual environment in $SCRIPT_DIR/.venv"
    python3 -m venv .venv
fi

# Activate the virtual environment
echo "Activating virtual environment"
source .venv/bin/activate

# Install or update dependencies
if [ -f "requirements.txt" ]; then
    echo "Verifying and/or installing dependencies"
    pip install --upgrade pip
    pip install -r requirements.txt
else
    echo "Warning: requirements.txt not found in $SCRIPT_DIR"
fi

# Set PYTHONPATH
export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"

# Check if hackrf_sweep is available on the system
if ! command -v hackrf_sweep &> /dev/null; then
    echo -e "\nWARNING: 'hackrf_sweep' utility not found."
    echo -e "HackRF radio will not be a usable SDR for scanning."
    echo ""
fi

# Launch the selected application
echo "Launching application: $APP_NAME $PYTHON_ARGS"
python3 "$APP_PATH" $PYTHON_ARGS

# Deactivate the virtual environment when the GUI is closed
deactivate
echo "Application closed safely."

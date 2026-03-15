import sys
import logging
import argparse
from PyQt5.QtWidgets import QApplication
from scanner.scanner_window import ScannerWindow

def setup_logging(log_level):
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

def main():
    parser = argparse.ArgumentParser(description="SDR Spectrum Scanner")
    parser.add_argument('--verbose', action='store_true', help="Enable debug level logging")
    args, unknown = parser.parse_known_args()
    
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(log_level)
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = ScannerWindow()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()

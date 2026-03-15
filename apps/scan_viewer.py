import sys
import logging
from PyQt5.QtWidgets import QApplication
import pyqtgraph as pg
from viewer.viewer_window import ViewerWindow

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )

def main():
    setup_logging()
    
    pg.setConfigOptions(antialias=False)
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = ViewerWindow()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()

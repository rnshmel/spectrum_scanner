import pyqtgraph as pg
from PyQt5.QtWidgets import QMainWindow, QTabWidget, QAction, QWidget
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import Qt

# Import our tabs
from viewer.tabs.single_file import SingleFileTab
from viewer.tabs.multi_concurrent import MultiConcurrentTab
from viewer.tabs.temporal_overview import TemporalOverviewTab

class ViewerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SDR Spectrum Viewer")
        self.resize(1300, 850) 
        
        self.is_dark_mode = True
        
        self._init_ui()
        self.apply_theme()

    def _init_ui(self):
        menubar = self.menuBar()
        view_menu = menubar.addMenu('View')
        
        self.theme_action = QAction('Switch to Light Mode', self)
        self.theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(self.theme_action)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.tab_single = SingleFileTab()
        self.tab_multi_concurrent = MultiConcurrentTab()
        self.tab_temporal = TemporalOverviewTab()

        self.tabs.addTab(self.tab_single, "Single File")
        self.tabs.addTab(self.tab_multi_concurrent, "Multi File")
        self.tabs.addTab(self.tab_temporal, "Subscan Spectrogram")

    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.theme_action.setText('Switch to Light Mode' if self.is_dark_mode else 'Switch to Dark Mode')
        self.apply_theme()
        
        self.tab_single.update_theme(self.is_dark_mode)
        self.tab_multi_concurrent.update_theme(self.is_dark_mode)
        self.tab_temporal.update_theme(self.is_dark_mode)

    def apply_theme(self):
        app = self.window().parent() if self.window().parent() else self
        palette = QPalette()
        
        if self.is_dark_mode:
            palette.setColor(QPalette.Window, QColor(53, 53, 53))
            palette.setColor(QPalette.WindowText, Qt.white)
            palette.setColor(QPalette.Base, QColor(25, 25, 25))
            palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
            palette.setColor(QPalette.ToolTipBase, Qt.white)
            palette.setColor(QPalette.ToolTipText, Qt.white)
            palette.setColor(QPalette.Text, Qt.white)
            palette.setColor(QPalette.Button, QColor(53, 53, 53))
            palette.setColor(QPalette.ButtonText, Qt.white)
            palette.setColor(QPalette.BrightText, Qt.red)
            palette.setColor(QPalette.Link, QColor(42, 130, 218))
            palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
            palette.setColor(QPalette.HighlightedText, Qt.black)
        else:
            palette = self.style().standardPalette()
            
        self.setPalette(palette)

import os
import datetime
import logging
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QFormLayout, QComboBox, QSpinBox, 
                             QLineEdit, QPushButton, QCheckBox, QLabel, QFileDialog, 
                             QGroupBox, QMessageBox, QPlainTextEdit)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject

from scanner.orchestrator import ScanOrchestrator
from scanner.radio.hackrf import HackRFBackend

class LogEmitter(QObject):
    new_log = pyqtSignal(str)

class GUILogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.emitter = LogEmitter()
        self.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', '%H:%M:%S'))

    def emit(self, record):
        msg = self.format(record)
        self.emitter.new_log.emit(msg)

class ScannerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SDR Survey Tool")
        self.setMinimumWidth(600)

        self.radio_backend = None
        self.orchestrator = None
        self.duration_timer = QTimer()
        self.duration_timer.setSingleShot(True)
        self.duration_timer.timeout.connect(self.graceful_stop)

        self._init_ui()
        self._setup_orchestrator()
        self._setup_gui_logger()

    def _setup_gui_logger(self):
        self.gui_logger = GUILogHandler()
        self.gui_logger.setLevel(logging.INFO)
        self.gui_logger.emitter.new_log.connect(self.console_output.appendPlainText)
        logging.getLogger().addHandler(self.gui_logger)

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        hw_group = QGroupBox("Radio Hardware")
        hw_layout = QFormLayout()
        self.combo_radio = QComboBox()
        self.combo_radio.addItems(["HackRF"]) 
        hw_layout.addRow("Select SDR:", self.combo_radio)
        hw_group.setLayout(hw_layout)
        main_layout.addWidget(hw_group)

        radio_group = QGroupBox("Radio Settings (HackRF Defaults)")
        radio_layout = QFormLayout()
        
        self.spin_rf_gain = QSpinBox(); self.spin_rf_gain.setRange(0, 14); self.spin_rf_gain.setValue(0)
        self.spin_if_gain = QSpinBox(); self.spin_if_gain.setRange(0, 40); self.spin_if_gain.setValue(16)
        self.spin_bb_gain = QSpinBox(); self.spin_bb_gain.setRange(0, 62); self.spin_bb_gain.setValue(18)
        
        self.spin_bin_width = QSpinBox()
        self.spin_bin_width.setRange(2445, 5000000)
        self.spin_bin_width.setValue(10000)
        self.spin_bin_width.setSuffix(" Hz")

        radio_layout.addRow("RF Gain (Amp):", self.spin_rf_gain)
        radio_layout.addRow("IF Gain (LNA):", self.spin_if_gain)
        radio_layout.addRow("BB Gain (VGA):", self.spin_bb_gain)
        radio_layout.addRow("FFT Bin Width:", self.spin_bin_width)
        radio_group.setLayout(radio_layout)
        main_layout.addWidget(radio_group)

        scan_group = QGroupBox("Scan Parameters")
        scan_layout = QFormLayout()

        self.spin_start_freq = QSpinBox(); self.spin_start_freq.setRange(1, 6000); self.spin_start_freq.setValue(100); self.spin_start_freq.setSuffix(" MHz")
        self.spin_stop_freq = QSpinBox(); self.spin_stop_freq.setRange(1, 6000); self.spin_stop_freq.setValue(500); self.spin_stop_freq.setSuffix(" MHz")
        
        dur_layout = QHBoxLayout()
        self.spin_dur_hours = QSpinBox(); self.spin_dur_hours.setRange(0, 999); self.spin_dur_hours.setSuffix(" hrs")
        self.spin_dur_mins = QSpinBox(); self.spin_dur_mins.setRange(0, 59); self.spin_dur_mins.setSuffix(" mins")
        self.spin_dur_hours.setValue(1)
        dur_layout.addWidget(self.spin_dur_hours)
        dur_layout.addWidget(self.spin_dur_mins)

        scan_layout.addRow("Start Frequency:", self.spin_start_freq)
        scan_layout.addRow("Stop Frequency:", self.spin_stop_freq)
        scan_layout.addRow("Scan Duration:", dur_layout)
        scan_group.setLayout(scan_layout)
        main_layout.addWidget(scan_group)

        file_group = QGroupBox("Output Settings")
        file_layout = QFormLayout()

        dir_layout = QHBoxLayout()
        self.le_save_dir = QLineEdit(os.getcwd())
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self.browse_directory)
        dir_layout.addWidget(self.le_save_dir)
        dir_layout.addWidget(btn_browse)

        name_layout = QHBoxLayout()
        self.le_filename = QLineEdit()
        btn_autogen = QPushButton("Auto Gen")
        btn_autogen.clicked.connect(self.generate_filename)
        name_layout.addWidget(self.le_filename)
        name_layout.addWidget(btn_autogen)

        subscan_layout = QHBoxLayout()
        self.chk_subscan = QCheckBox("Enable Subscans")
        self.spin_subscan_interval = QSpinBox()
        self.spin_subscan_interval.setRange(1, 999); self.spin_subscan_interval.setValue(30); self.spin_subscan_interval.setSuffix(" mins")
        self.spin_subscan_interval.setEnabled(False)
        self.chk_subscan.toggled.connect(self.spin_subscan_interval.setEnabled)
        subscan_layout.addWidget(self.chk_subscan)
        subscan_layout.addWidget(self.spin_subscan_interval)

        file_layout.addRow("Save Directory:", dir_layout)
        file_layout.addRow("Base Filename:", name_layout)
        file_layout.addRow("Subscans:", subscan_layout)
        file_group.setLayout(file_layout)
        main_layout.addWidget(file_group)

        control_layout = QHBoxLayout()
        self.btn_start = QPushButton("START SCAN")
        self.btn_start.setStyleSheet("font-weight: bold; background-color: #4CAF50; color: white; padding: 10px;")
        self.btn_start.clicked.connect(self.start_scan)
        
        self.btn_stop = QPushButton("STOP EARLY")
        self.btn_stop.setStyleSheet("font-weight: bold; background-color: #f44336; color: white; padding: 10px;")
        self.btn_stop.clicked.connect(self.early_stop)
        self.btn_stop.setEnabled(False)

        control_layout.addWidget(self.btn_start)
        control_layout.addWidget(self.btn_stop)
        main_layout.addLayout(control_layout)

        self.lbl_status = QLabel("Ready.")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet("font-weight: bold; color: #555;")
        main_layout.addWidget(self.lbl_status)

        self.console_output = QPlainTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: monospace;")
        self.console_output.setMaximumHeight(200)
        main_layout.addWidget(self.console_output)

        self.generate_filename()

    def _setup_orchestrator(self):
        self.radio_backend = HackRFBackend()
        self.orchestrator = ScanOrchestrator(self.radio_backend)
        
        self.orchestrator.status_msg.connect(self.update_status)
        self.orchestrator.scan_started.connect(self.on_scan_started)
        self.orchestrator.scan_stopped.connect(self.on_scan_stopped)
        self.orchestrator.error_occurred.connect(self.on_error)
        self.orchestrator.hardware_reset_required.connect(self.prompt_hardware_reset)

    def browse_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Save Directory")
        if dir_path:
            self.le_save_dir.setText(dir_path)

    def generate_filename(self):
        start = self.spin_start_freq.value()
        stop = self.spin_stop_freq.value()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.le_filename.setText(f"scan_{start}M_{stop}M_{timestamp}.dat")

    def start_scan(self):
            total_minutes = (self.spin_dur_hours.value() * 60) + self.spin_dur_mins.value()
            if total_minutes <= 0:
                QMessageBox.warning(self, "Invalid Input", "Scan duration must be > 0.")
                return
                
            config = {
                'start_freq': self.spin_start_freq.value(),
                'stop_freq': self.spin_stop_freq.value(),
                'bin_width': self.spin_bin_width.value(),
                'rf_gain': self.spin_rf_gain.value(),
                'if_gain': self.spin_if_gain.value(),
                'bb_gain': self.spin_bb_gain.value(),
                'save_dir': self.le_save_dir.text(),
                'base_filename': self.le_filename.text(),
                'subscan_enabled': self.chk_subscan.isChecked(),
                'subscan_interval_min': self.spin_subscan_interval.value(),
                'scan_duration_sec': total_minutes * 60
            }

            self.orchestrator.configure(config)
            self.orchestrator.start()
            self.duration_timer.start(total_minutes * 60 * 1000)

    def graceful_stop(self):
            self.stop_scan(early=False)

    def early_stop(self):
        self.duration_timer.stop()
        self.stop_scan(early=True)

    def stop_scan(self, early=True):
        if self.orchestrator and self.orchestrator.isRunning():
            self.orchestrator.stop(early_termination=early)
            self.btn_stop.setEnabled(False)

    def update_status(self, msg: str):
        self.lbl_status.setText(msg)

    def on_scan_started(self):
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._toggle_inputs(False)

    def on_scan_stopped(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._toggle_inputs(True)
        self.update_status("Scan Complete / Stopped.")

    def on_error(self, err_msg: str):
        QMessageBox.critical(self, "Scan Error", err_msg)
        self.stop_scan()

    def prompt_hardware_reset(self):
        QMessageBox.critical(self, "Hardware Locked", "Fatal error: SDR hardware reset required.")

    def _toggle_inputs(self, state: bool):
        self.spin_start_freq.setEnabled(state)
        self.spin_stop_freq.setEnabled(state)
        self.spin_dur_hours.setEnabled(state)
        self.spin_dur_mins.setEnabled(state)
        self.chk_subscan.setEnabled(state)
        if state and self.chk_subscan.isChecked():
            self.spin_subscan_interval.setEnabled(True)
        else:
            self.spin_subscan_interval.setEnabled(state)

    def closeEvent(self, event):
        if self.orchestrator and self.orchestrator.isRunning():
            reply = QMessageBox.question(self, 'Exit', "Stop scan and exit?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.early_stop()
                self.orchestrator.wait(3000)
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

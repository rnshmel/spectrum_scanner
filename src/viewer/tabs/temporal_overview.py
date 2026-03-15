import os
import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFileDialog, QGroupBox, 
                             QMessageBox, QComboBox, QSpinBox, 
                             QDialog, QScrollArea, QFrame, QProgressDialog)
from PyQt5.QtCore import Qt, QRectF

from viewer.data_parser import DatFileParser
from viewer.dsp_utils import SpectrumFilters

class FilterTuningDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tune DSP Smoothing")
        self.resize(800, 500)
        
        self.current_data_db = None
        self.current_x_axis = None
        
        self.applied_filter_type = "None"
        self.applied_filter_len = 5
        
        layout = QVBoxLayout(self)
        
        # Plot
        pg.setConfigOption('background', '#191919')
        pg.setConfigOption('foreground', 'w')
        self.plot_widget = pg.PlotWidget(title="Preview Smoothing Filter")
        self.plot_widget.setLabel('bottom', 'Frequency', units='MHz')
        self.plot_widget.setLabel('left', 'Power', units='dB')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.curve = self.plot_widget.plot(pen='g')
        layout.addWidget(self.plot_widget, stretch=1)
        
        # Controls
        ctrl_layout = QHBoxLayout()
        
        self.btn_load = QPushButton("Load Sample .dat")
        self.btn_load.clicked.connect(self.load_sample)
        
        self.combo_filter = QComboBox()
        self.combo_filter.addItems(["None", "Moving Average", "Gaussian"])
        self.combo_filter.currentIndexChanged.connect(self.update_plot)
        
        self.spin_filter_len = QSpinBox()
        self.spin_filter_len.setRange(3, 999)
        self.spin_filter_len.setSingleStep(2)
        self.spin_filter_len.setValue(5)
        self.spin_filter_len.valueChanged.connect(self._on_filter_len_changed)
        
        self.btn_apply = QPushButton("Apply to Spectrogram")
        self.btn_apply.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn_apply.clicked.connect(self.accept_settings)
        
        ctrl_layout.addWidget(self.btn_load)
        ctrl_layout.addWidget(QLabel("Filter Type:"))
        ctrl_layout.addWidget(self.combo_filter)
        ctrl_layout.addWidget(QLabel("Length:"))
        ctrl_layout.addWidget(self.spin_filter_len)
        ctrl_layout.addStretch()
        ctrl_layout.addWidget(self.btn_apply)
        
        layout.addLayout(ctrl_layout)

    def load_sample(self):
        fpath, _ = QFileDialog.getOpenFileName(None, "Open Sample File", "", "Data Files (*.dat)")
        if not fpath: return
        
        data = DatFileParser.parse(fpath)
        if data:
            self.current_data_db = data.data_db
            self.current_x_axis = np.linspace(data.start_freq_mhz, data.stop_freq_mhz, len(data.data_db))
            self.update_plot()
            self.plot_widget.autoRange()

    def _on_filter_len_changed(self, val):
        if val % 2 == 0:
            self.spin_filter_len.blockSignals(True)
            self.spin_filter_len.setValue(val + 1)
            self.spin_filter_len.blockSignals(False)
        self.update_plot()

    def update_plot(self):
        if self.current_data_db is None: return
        
        ftype = self.combo_filter.currentText()
        flen = self.spin_filter_len.value()
        
        if ftype == "None" or flen < 3:
            filtered = self.current_data_db
        elif ftype == "Moving Average":
            filtered = SpectrumFilters.apply_moving_average(self.current_data_db, flen)
        elif ftype == "Gaussian":
            filtered = SpectrumFilters.apply_gaussian(self.current_data_db, flen)
            
        self.curve.setData(self.current_x_axis, filtered)

    def accept_settings(self):
        self.applied_filter_type = self.combo_filter.currentText()
        self.applied_filter_len = self.spin_filter_len.value()
        self.accept()


class TemporalOverviewTab(QWidget):
    def __init__(self):
        super().__init__()
        
        self.filter_type = "None"
        self.filter_len = 5
        self.spectrogram_data = None
        
        self.tuning_dialog = FilterTuningDialog(self)
        
        self._init_ui()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        plot_layout = QHBoxLayout()
        
        pg.setConfigOption('background', '#191919')
        pg.setConfigOption('foreground', 'w')
        
        self.plot_widget = pg.PlotWidget(title="Temporal Spectrogram (Waterfall)")
        self.plot_widget.setLabel('bottom', 'Frequency', units='MHz')
        self.plot_widget.setLabel('left', 'Time / Subscan Index')
        
        self.image_item = pg.ImageItem()
        self.plot_widget.addItem(self.image_item)
        
        self.hist_widget = pg.HistogramLUTWidget()
        self.hist_widget.setImageItem(self.image_item)
        self.hist_widget.setMaximumWidth(120)
        
        colormap = pg.colormap.get('viridis')
        self.hist_widget.gradient.setColorMap(colormap)
        
        plot_layout.addWidget(self.plot_widget, stretch=5)
        plot_layout.addWidget(self.hist_widget, stretch=1)
        main_layout.addLayout(plot_layout, stretch=4)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        scroll_content = QWidget()
        cmd_layout = QVBoxLayout(scroll_content)
        cmd_layout.setAlignment(Qt.AlignTop)

        dsp_group = QGroupBox("1. DSP Pre-Processing")
        dsp_layout = QVBoxLayout()
        
        self.lbl_current_dsp = QLabel(f"Current Filter: {self.filter_type}")
        self.lbl_current_dsp.setStyleSheet("font-weight: bold; color: #4CAF50;")
        
        self.btn_tune = QPushButton("Open Tuning Window")
        self.btn_tune.clicked.connect(self.open_tuning_dialog)
        
        dsp_layout.addWidget(self.lbl_current_dsp)
        dsp_layout.addWidget(self.btn_tune)
        dsp_group.setLayout(dsp_layout)
        cmd_layout.addWidget(dsp_group)

        data_group = QGroupBox("2. Bulk Ingest")
        data_layout = QVBoxLayout()
        
        self.btn_load_dir = QPushButton("Load Subscan Directory")
        self.btn_load_dir.clicked.connect(self.process_directory)
        
        self.lbl_data_status = QLabel("Ready.")
        self.lbl_data_status.setWordWrap(True)
        
        data_layout.addWidget(self.btn_load_dir)
        data_layout.addWidget(self.lbl_data_status)
        data_group.setLayout(data_layout)
        cmd_layout.addWidget(data_group)

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, stretch=1)

    def open_tuning_dialog(self):
        if self.tuning_dialog.exec_() == QDialog.Accepted:
            self.filter_type = self.tuning_dialog.applied_filter_type
            self.filter_len = self.tuning_dialog.applied_filter_len
            
            if self.filter_type == "None":
                self.lbl_current_dsp.setText("Current Filter: None")
            else:
                self.lbl_current_dsp.setText(f"Current Filter: {self.filter_type} (Len: {self.filter_len})")

    def process_directory(self):
        dir_path = QFileDialog.getExistingDirectory(None, "Select Subscan Directory")
        if not dir_path: return

        # Find and strictly filter for _N.dat files
        all_files = os.listdir(dir_path)
        subscans = []
        for f in all_files:
            if f.endswith('.dat'):
                # Extract the N from scan_XXXX_N.dat
                parts = f.replace('.dat', '').split('_')
                if parts and parts[-1].isdigit():
                    idx = int(parts[-1])
                    subscans.append((idx, os.path.join(dir_path, f)))
        
        if not subscans:
            QMessageBox.warning(self, "No Subscans", "Could not find any files ending with an integer index (ex. *_1.dat) in this directory.")
            return

        # Sort mathematically by index
        subscans.sort(key=lambda x: x[0])
        filepaths = [s[1] for s in subscans]

        progress = QProgressDialog("Generating Spectrogram.", "Cancel", 0, len(filepaths), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        data_rows = []
        meta_start_mhz = 0
        meta_stop_mhz = 0
        
        for i, fpath in enumerate(filepaths):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            
            data = DatFileParser.parse(fpath)
            if not data or len(data.data_db) == 0:
                continue
                
            if i == 0:
                meta_start_mhz = data.start_freq_mhz
                meta_stop_mhz = data.stop_freq_mhz
                
            raw_db = data.data_db
            
            # Apply chosen filter
            if self.filter_type == "None" or self.filter_len < 3:
                filt_db = raw_db
            elif self.filter_type == "Moving Average":
                filt_db = SpectrumFilters.apply_moving_average(raw_db, self.filter_len)
            elif self.filter_type == "Gaussian":
                filt_db = SpectrumFilters.apply_gaussian(raw_db, self.filter_len)
                
            data_rows.append(filt_db)

        progress.setValue(len(filepaths))

        if not data_rows:
            self.lbl_data_status.setText("Error: No valid data parsed.")
            return

        self.spectrogram_data = np.vstack(data_rows)
        num_scans, num_bins = self.spectrogram_data.shape
        
        # pyqtgraph ImageItem expects data in (x, y) orientation. 
        # vstack makes it (Time, Freq). We transpose to (Freq, Time)
        self.image_item.setImage(self.spectrogram_data.T)
        
        # Geographically map the pixels to real MHz
        span_mhz = meta_stop_mhz - meta_start_mhz
        rect = QRectF(meta_start_mhz, 0, span_mhz, num_scans)
        self.image_item.setRect(rect)
        
        # Auto-level the colorbar based on actual data bounds
        self.hist_widget.setLevels(np.min(self.spectrogram_data), np.max(self.spectrogram_data))
        self.plot_widget.autoRange()
        
        self.lbl_data_status.setText(f"Spectrogram built successfully.\n\nFiles: {num_scans}\nSpan: {meta_start_mhz} - {meta_stop_mhz} MHz")

    def update_theme(self, is_dark: bool):
        bg = '#191919' if is_dark else '#F0F0F0'
        fg = 'w' if is_dark else 'k'
        
        self.plot_widget.setBackground(bg)
        self.tuning_dialog.plot_widget.setBackground(bg)
        
        for plot in [self.plot_widget, self.tuning_dialog.plot_widget]:
            plot.getAxis('bottom').setPen(fg)
            plot.getAxis('left').setPen(fg)
            plot.getAxis('bottom').setTextPen(fg)
            plot.getAxis('left').setTextPen(fg)

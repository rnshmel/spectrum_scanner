import os
import csv
import pyqtgraph as pg
import numpy as np
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFileDialog, QGroupBox, QColorDialog, QSlider, 
                             QMessageBox, QComboBox, QSpinBox, QCheckBox, QDoubleSpinBox,
                             QDialog, QTableWidget, QTableWidgetItem, QHeaderView, 
                             QScrollArea, QFrame, QProgressDialog)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QColor

from viewer.data_parser import DatFileParser
from viewer.dsp_utils import SpectrumFilters

class NumericTableItem(QTableWidgetItem):
    def __init__(self, value, format_str="{:.2f}"):
        if isinstance(value, str):
            super().__init__(value)
            self.value = 0.0 # Fallback for text columns
        else:
            super().__init__(format_str.format(value))
            self.value = float(value)
            
    def __lt__(self, other):
        if isinstance(other, NumericTableItem) and not isinstance(self.value, str):
            return self.value < other.value
        return super().__lt__(other)

class MultiPeakTableDialog(QDialog):
    def __init__(self, title="Detected Signal Peaks", parent=None):
        super().__init__(parent)
        
        # Overwrite default QDialog flags entirely to force standard OS Window controls
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        
        self.setWindowTitle(title)
        self.resize(650, 600)
        
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Source Signal", "Frequency (MHz)", "Power (dB)", "Prominence (dB)", "Width (kHz)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSortingEnabled(True)
        
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        self.btn_export = QPushButton("Export to CSV")
        self.btn_export.clicked.connect(self.export_csv)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_export)
        layout.addLayout(btn_layout)

    def update_data(self, all_peaks_data):
        self.table.setSortingEnabled(False) 
        self.table.setRowCount(len(all_peaks_data))
        
        for row, peak in enumerate(all_peaks_data):
            self.table.setItem(row, 0, QTableWidgetItem(peak['source']))
            self.table.setItem(row, 1, NumericTableItem(peak['freq'], "{:.3f}"))
            self.table.setItem(row, 2, NumericTableItem(peak['power'], "{:.2f}"))
            self.table.setItem(row, 3, NumericTableItem(peak['prominence'], "{:.2f}"))
            self.table.setItem(row, 4, NumericTableItem(peak['width_khz'], "{:.1f}"))
            
        self.table.setSortingEnabled(True)
        
    def export_csv(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "Export", "No peak data available to export.")
            return
            
        path, _ = QFileDialog.getSaveFileName(None, "Export Peaks CSV", "concurrent_peaks.csv", "CSV Files (*.csv)")
        if path:
            try:
                with open(path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    headers = [self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())]
                    writer.writerow(headers)
                    for row in range(self.table.rowCount()):
                        row_data = [self.table.item(row, col).text() if self.table.item(row, col) else "" for col in range(self.table.columnCount())]
                        writer.writerow(row_data)
                QMessageBox.information(self, "Export Successful", f"Saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

class ClusterTableDialog(QDialog):
    def __init__(self, title="Signal Clustering Analysis", parent=None):
        super().__init__(parent)
        
        # Overwrite default QDialog flags entirely to force standard OS Window controls
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        
        self.setWindowTitle(title)
        self.resize(850, 750) 
        
        self.current_peaks = []
        self.total_sources = 1
        self.all_x = []
        self.all_y = []
        
        # Predefined qualitative colors for different clusters (Noise is always Grey)
        self.palette = ['#00FF00', '#00FFFF', '#FF00FF', '#FFFF00', '#FF8C00', '#00BFFF', '#FF1493']
        
        layout = QVBoxLayout(self)
        
        ctrl_layout = QHBoxLayout()
        self.spin_eps = QDoubleSpinBox()
        self.spin_eps.setRange(0.001, 50.0)
        self.spin_eps.setDecimals(3)
        self.spin_eps.setSingleStep(0.05)
        self.spin_eps.setValue(0.100) 
        self.spin_eps.valueChanged.connect(self.recalculate)
        
        self.spin_min_samples = QSpinBox()
        self.spin_min_samples.setRange(1, 1000)
        self.spin_min_samples.setValue(1) 
        self.spin_min_samples.valueChanged.connect(self.recalculate)
        
        self.btn_autoscale_y = QPushButton("Auto Scale Y (View)")
        self.btn_autoscale_y.clicked.connect(self.autoscale_y)
        
        ctrl_layout.addWidget(QLabel("DBSCAN Epsilon (MHz):"))
        ctrl_layout.addWidget(self.spin_eps)
        ctrl_layout.addWidget(QLabel("Min Hits to Form Signal:"))
        ctrl_layout.addWidget(self.spin_min_samples)
        ctrl_layout.addStretch()
        ctrl_layout.addWidget(self.btn_autoscale_y)
        layout.addLayout(ctrl_layout)
        
        # 2D Scatter Plot and Minimap
        pg.setConfigOption('background', '#191919')
        pg.setConfigOption('foreground', 'w')
        
        plot_layout = QVBoxLayout()
        
        self.plot_widget = pg.PlotWidget(title="Freq vs. Width (Cluster Space)")
        self.plot_widget.setLabel('bottom', 'Center Frequency', units='MHz')
        self.plot_widget.setLabel('left', 'Bandwidth', units='kHz')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLimits(xMin=0, yMin=0) 
        
        self.minimap_widget = pg.PlotWidget()
        self.minimap_widget.setMaximumHeight(120)
        self.minimap_widget.hideAxis('left')
        self.minimap_widget.setLimits(xMin=0, yMin=0) 
        
        self.region = pg.LinearRegionItem(pen=pg.mkPen(color='w', width=3), hoverPen=pg.mkPen(color='#2a82da', width=5))
        self.region.setZValue(10)
        self.minimap_widget.addItem(self.region)

        self.region.sigRegionChanged.connect(self.update_main_plot_range)
        self.plot_widget.sigRangeChanged.connect(self.update_minimap_region)
        
        plot_layout.addWidget(self.plot_widget, stretch=4)
        plot_layout.addWidget(self.minimap_widget, stretch=1)
        layout.addLayout(plot_layout, stretch=3)
        
        # Aggregate Signal Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Signal ID", "Status", "Avg Freq (MHz)", "Peak Power (dB)", "Avg Width (kHz)", "Total Hits"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table, stretch=3)

        # Export Button Row
        export_layout = QHBoxLayout()
        self.btn_export = QPushButton("Export Clusters to CSV")
        self.btn_export.clicked.connect(self.export_csv)
        export_layout.addStretch()
        export_layout.addWidget(self.btn_export)
        layout.addLayout(export_layout)
        
    def set_peaks_data(self, peaks_data, total_sources=1):
        self.current_peaks = peaks_data
        self.total_sources = total_sources
        self.recalculate()

    def recalculate(self):
        self.plot_widget.clear()
        self.minimap_widget.clear()
        self.minimap_widget.addItem(self.region) 
        
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.all_x = []
        self.all_y = []
        
        if not self.current_peaks:
            self.table.setSortingEnabled(True)
            return

        freqs = [p['freq'] for p in self.current_peaks]
        widths = [p['width_khz'] for p in self.current_peaks]
        powers = [p['power'] for p in self.current_peaks]
        proms = [p['prominence'] for p in self.current_peaks]
        sources = [p['source'] for p in self.current_peaks]
        
        clusters = SpectrumFilters.cluster_peaks(
            freqs, widths, powers, proms, sources=sources,
            eps=self.spin_eps.value(), 
            min_samples=self.spin_min_samples.value()
        )
        
        self.table.setRowCount(len(clusters))
        
        for row, cl in enumerate(clusters):
            self.all_x.extend(cl['raw_freqs'])
            self.all_y.extend(cl['raw_widths'])
            
            total = max(1, self.total_sources)
            percent = (cl['unique_sources'] / total) * 100
            status_text = f"{percent:.0f}% ({cl['unique_sources']}/{total})"

            if cl['is_noise']:
                color = QColor(100, 100, 100, 150) 
            else:
                c_idx = row % len(self.palette)
                color = QColor(self.palette[c_idx])
            
            scatter_main = pg.ScatterPlotItem(x=cl['raw_freqs'], y=cl['raw_widths'], size=12, pen=pg.mkPen(None), brush=pg.mkBrush(color))
            scatter_mini = pg.ScatterPlotItem(x=cl['raw_freqs'], y=cl['raw_widths'], size=5, pen=pg.mkPen(None), brush=pg.mkBrush(color))
            
            self.plot_widget.addItem(scatter_main)
            self.minimap_widget.addItem(scatter_mini)
            
            self.table.setItem(row, 0, QTableWidgetItem(cl['cluster_id']))
            self.table.setItem(row, 1, QTableWidgetItem(status_text))
            self.table.setItem(row, 2, NumericTableItem(cl['avg_freq'], "{:.3f}"))
            self.table.setItem(row, 3, NumericTableItem(cl['peak_power'], "{:.2f}"))
            self.table.setItem(row, 4, NumericTableItem(cl['avg_width'], "{:.1f}"))
            self.table.setItem(row, 5, NumericTableItem(cl['hit_count'], "{:.0f}"))
            
            self.table.item(row, 0).setBackground(color)
            if not cl['is_noise']:
                self.table.item(row, 0).setForeground(QColor('black'))
            
        self.table.setSortingEnabled(True)
        
        if len(freqs) > 0:
            min_f, max_f = min(freqs), max(freqs)
            min_w, max_w = min(widths), max(widths)
            
            self.minimap_widget.setXRange(max(0, min_f - 1), max_f + 1, padding=0)
            self.minimap_widget.setYRange(0, max_w * 1.1, padding=0)
            
            self.region.setBounds([0, max_f + 10])
            self.region.setRegion([max(0, min_f - 1), max_f + 1])
            self.autoscale_y()

    def update_main_plot_range(self, region):
        self.plot_widget.setXRange(*region.getRegion(), padding=0)

    def update_minimap_region(self, window, viewRange):
        self.region.setRegion(viewRange[0])

    def autoscale_y(self):
        if not self.all_x or not self.all_y:
            return
            
        x_min, x_max = self.plot_widget.viewRange()[0]
        x_arr = np.array(self.all_x)
        y_arr = np.array(self.all_y)
        
        mask = (x_arr >= x_min) & (x_arr <= x_max)
        vis_y = y_arr[mask] 
        
        if len(vis_y) > 0:
            y_max = float(np.max(vis_y))
            self.plot_widget.setYRange(0, y_max * 1.1, padding=0)

    def export_csv(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "Export", "No cluster data available to export.")
            return
            
        path, _ = QFileDialog.getSaveFileName(None, "Export Clusters CSV", "signal_clusters.csv", "CSV Files (*.csv)")
        if path:
            try:
                with open(path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    headers = [self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())]
                    writer.writerow(headers)
                    for row in range(self.table.rowCount()):
                        row_data = [self.table.item(row, col).text() if self.table.item(row, col) else "" for col in range(self.table.columnCount())]
                        writer.writerow(row_data)
                QMessageBox.information(self, "Export Successful", f"Saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))


class SignalSlotWidget(QFrame):
    data_changed = pyqtSignal()
    style_changed = pyqtSignal()
    remove_requested = pyqtSignal(object)

    def __init__(self, slot_id, default_color):
        super().__init__()
        self.slot_id = slot_id
        
        self.setObjectName("SignalSlot")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Sunken)
        self.setStyleSheet("#SignalSlot { background-color: rgba(100, 100, 100, 20); border-radius: 5px; margin-bottom: 5px; }")

        self.parsed_data = None
        self.x_axis = None
        self.noise_floor = -100.0
        self.color = default_color
        self.opacity = 255 

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        header_layout = QHBoxLayout()
        self.lbl_filename = QLabel(f"Slot {slot_id}: Empty")
        self.lbl_filename.setStyleSheet("font-weight: bold; color: #888;")
        self.lbl_filename.setWordWrap(True)
        self.btn_remove = QPushButton("X")
        self.btn_remove.setMaximumWidth(30)
        self.btn_remove.setStyleSheet("color: #FF3333; font-weight: bold;")
        self.btn_remove.clicked.connect(lambda: self.remove_requested.emit(self))
        header_layout.addWidget(self.lbl_filename)
        header_layout.addWidget(self.btn_remove)
        
        self.lbl_meta = QLabel("Span: --")
        
        self.btn_load = QPushButton("Load File")
        self.btn_load.clicked.connect(self._load_file)

        style_layout = QHBoxLayout()
        self.btn_color = QPushButton("Color")
        self.btn_color.setStyleSheet(f"background-color: {self.color.name()}; color: black; font-weight: bold;")
        self.btn_color.clicked.connect(self._choose_color)
        
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(0, 255)
        self.slider_opacity.setValue(self.opacity)
        self.slider_opacity.valueChanged.connect(self._change_opacity)
        
        style_layout.addWidget(self.btn_color)
        style_layout.addWidget(QLabel("Op:"))
        style_layout.addWidget(self.slider_opacity)

        layout.addLayout(header_layout)
        layout.addWidget(self.lbl_meta)
        layout.addWidget(self.btn_load)
        layout.addLayout(style_layout)

    def _load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(None, "Open Scan File", "", "Data Files (*.dat)")
        if not file_path: return

        data = DatFileParser.parse(file_path)
        if not data:
            QMessageBox.critical(self, "Error", "Failed to parse .dat file.")
            return

        self.parsed_data = data
        self.lbl_filename.setText(os.path.basename(file_path))
        self.lbl_filename.setStyleSheet("font-weight: bold; color: #4CAF50;")
        self.lbl_meta.setText(f"{data.start_freq_mhz}M - {data.stop_freq_mhz}M")
        
        self.x_axis = np.linspace(data.start_freq_mhz, data.stop_freq_mhz, len(data.data_db))
        self.noise_floor = float(np.min(data.data_db))
        
        self.data_changed.emit()

    def _choose_color(self):
        c = QColorDialog.getColor(self.color, self, "Select Signal Color")
        if c.isValid():
            self.color = c
            self.btn_color.setStyleSheet(f"background-color: {self.color.name()}; color: black; font-weight: bold;")
            self.style_changed.emit()

    def _change_opacity(self, val):
        self.opacity = val
        self.style_changed.emit()

class MultiConcurrentTab(QWidget):
    def __init__(self):
        super().__init__()
        
        self.signal_slots = []
        self.slot_counter = 1
        self.color_palette = ['#00FF00', '#00FFFF', '#FF00FF', '#FFFF00', '#FF8C00'] 
        
        self.nf_color = QColor('#FFA500') 
        self.nf_3db_color = QColor('#FF3333') 
        
        # State for Headless Bulk Processing
        self.bulk_peaks = []
        self.bulk_file_count = 0
        
        # Completely separate Dialogs for Active vs Bulk data
        self.active_peak_dialog = MultiPeakTableDialog("Active Plotted Peaks", self)
        self.active_cluster_dialog = ClusterTableDialog("Active Plotted Clusters", self)
        
        self.bulk_peak_dialog = MultiPeakTableDialog("Bulk Processed Peaks", self)
        self.bulk_cluster_dialog = ClusterTableDialog("Bulk Processed Clusters", self)
        
        # Timer for debouncing heavy array slicing across multiple layers
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.refresh_plot_data)
        
        self._init_ui()
        self._add_signal_slot() 
        self._add_signal_slot()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        plot_layout = QVBoxLayout()
        
        pg.setConfigOption('background', '#191919')
        pg.setConfigOption('foreground', 'w')
        
        self.plot_widget = pg.PlotWidget(title="Concurrent Spectrum View")
        self.plot_widget.setLabel('left', 'Power', units='dB')
        self.plot_widget.setLabel('bottom', 'Frequency', units='MHz')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        self.minimap_widget = pg.PlotWidget()
        self.minimap_widget.setMaximumHeight(150)
        self.minimap_widget.setLabel('bottom', 'Frequency Overview', units='MHz')
        self.minimap_widget.hideAxis('left')
        
        self.region = pg.LinearRegionItem(pen=pg.mkPen(color='w', width=3), hoverPen=pg.mkPen(color='#4CAF50', width=5))
        self.region.setZValue(10)
        self.minimap_widget.addItem(self.region)

        self.region.sigRegionChanged.connect(self.on_region_changed)
        self.plot_widget.sigRangeChanged.connect(self.on_range_changed)

        plot_layout.addWidget(self.plot_widget, stretch=4)
        plot_layout.addWidget(self.minimap_widget, stretch=1)
        main_layout.addLayout(plot_layout, stretch=4)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setMinimumWidth(350)
        
        scroll_content = QWidget()
        cmd_layout = QVBoxLayout(scroll_content)
        cmd_layout.setAlignment(Qt.AlignTop)

        self.sources_group = QGroupBox("Active View Ports (Plotted)")
        self.sources_layout = QVBoxLayout()
        
        self.btn_add_slot = QPushButton("+ Add Signal Slot")
        self.btn_add_slot.clicked.connect(self._add_signal_slot)
        
        self.sources_layout.addWidget(self.btn_add_slot)
        self.sources_group.setLayout(self.sources_layout)
        cmd_layout.addWidget(self.sources_group)

        view_group = QGroupBox("View Controls")
        view_layout = QVBoxLayout()
        
        btn_layout = QHBoxLayout()
        self.btn_autoscale_x = QPushButton("Fit All (X)")
        self.btn_autoscale_x.clicked.connect(self.autoscale_x)
        self.btn_autoscale_y = QPushButton("Auto Scale Y")
        self.btn_autoscale_y.clicked.connect(self.autoscale_y)
        btn_layout.addWidget(self.btn_autoscale_x)
        btn_layout.addWidget(self.btn_autoscale_y)
        
        row_thresh = QHBoxLayout()
        self.lbl_active_points = QLabel("Max Visible Pts: --")
        self.lbl_active_points.setStyleSheet("font-size: 11px; color: #888; font-weight: bold;")
        self.lbl_active_points.setWordWrap(True)
        row_thresh.addWidget(self.lbl_active_points)
        
        row_thresh.addWidget(QLabel("1:1 Thresh:"))
        self.spin_plot_thresh = QSpinBox()
        self.spin_plot_thresh.setRange(1000, 5000000)
        self.spin_plot_thresh.setSingleStep(10000)
        self.spin_plot_thresh.setValue(50000)
        self.spin_plot_thresh.valueChanged.connect(self.refresh_plot_data)
        row_thresh.addWidget(self.spin_plot_thresh)
        
        view_layout.addLayout(btn_layout)
        view_layout.addLayout(row_thresh)
        view_group.setLayout(view_layout)
        cmd_layout.addWidget(view_group)

        dsp_group = QGroupBox("Global Signal Smoothing")
        dsp_layout = QVBoxLayout()
        
        self.combo_filter = QComboBox()
        self.combo_filter.addItems(["None", "Moving Average", "Gaussian"])
        self.combo_filter.currentIndexChanged.connect(self._process_and_plot)
        
        self.spin_filter_len = QSpinBox()
        self.spin_filter_len.setRange(3, 999)
        self.spin_filter_len.setSingleStep(2)
        self.spin_filter_len.setValue(5)
        self.spin_filter_len.valueChanged.connect(self._on_filter_len_changed)
        
        dsp_layout.addWidget(self.combo_filter)
        dsp_layout.addWidget(QLabel("Filter Length (bins):"))
        dsp_layout.addWidget(self.spin_filter_len)
        dsp_group.setLayout(dsp_layout)
        cmd_layout.addWidget(dsp_group)

        nf_group = QGroupBox("Global Noise Floor")
        nf_layout = QVBoxLayout()
        
        self.combo_nf_method = QComboBox()
        self.combo_nf_method.addItems(["None", "Sliding Average", "Sliding Median"])
        self.combo_nf_method.currentIndexChanged.connect(self._process_and_plot)
        
        self.spin_nf_len = QDoubleSpinBox()
        self.spin_nf_len.setRange(0.5, 999.0) 
        self.spin_nf_len.setSingleStep(0.5)
        self.spin_nf_len.setValue(3.0) 
        self.spin_nf_len.setSuffix(" MHz")
        self.spin_nf_len.valueChanged.connect(self._process_and_plot)
        
        nf_row_layout = QHBoxLayout()
        self.chk_show_nf = QCheckBox("Show Baselines")
        self.chk_show_nf.stateChanged.connect(self._on_nf_checkbox_changed)
        self.btn_nf_color = QPushButton("Color")
        self.btn_nf_color.setMaximumWidth(50)
        self.btn_nf_color.clicked.connect(self.choose_nf_color)
        nf_row_layout.addWidget(self.chk_show_nf)
        nf_row_layout.addWidget(self.btn_nf_color)
        
        db3_row_layout = QHBoxLayout()
        self.chk_show_3db = QCheckBox("Show Offsets")
        self.chk_show_3db.stateChanged.connect(self._on_nf_checkbox_changed)
        self.spin_nf_offset = QDoubleSpinBox()
        self.spin_nf_offset.setRange(0.5, 100.0)
        self.spin_nf_offset.setValue(3.0)
        self.spin_nf_offset.valueChanged.connect(self._process_and_plot)
        self.btn_3db_color = QPushButton("Color")
        self.btn_3db_color.setMaximumWidth(50)
        self.btn_3db_color.clicked.connect(self.choose_3db_color)
        db3_row_layout.addWidget(self.chk_show_3db)
        db3_row_layout.addWidget(self.spin_nf_offset)
        db3_row_layout.addWidget(self.btn_3db_color)
        
        nf_layout.addWidget(self.combo_nf_method)
        nf_layout.addWidget(QLabel("Window Size:"))
        nf_layout.addWidget(self.spin_nf_len)
        nf_layout.addLayout(nf_row_layout)
        nf_layout.addLayout(db3_row_layout)
        nf_group.setLayout(nf_layout)
        cmd_layout.addWidget(nf_group)

        peak_group = QGroupBox("Global Signal Analysis (Active Plots)")
        peak_layout = QVBoxLayout()
        
        peak_row = QHBoxLayout()
        self.chk_enable_peaks = QCheckBox("Detect Peaks")
        self.chk_enable_peaks.stateChanged.connect(self._process_and_plot)
        
        self.btn_view_active_peaks = QPushButton("Active Peaks")
        self.btn_view_active_peaks.clicked.connect(self.active_peak_dialog.show)
        
        self.btn_active_cluster = QPushButton("Active Clusters")
        self.btn_active_cluster.setStyleSheet("background-color: #2a82da; color: white; font-weight: bold;")
        self.btn_active_cluster.clicked.connect(self.active_cluster_dialog.show)
        
        peak_row.addWidget(self.chk_enable_peaks)
        peak_row.addWidget(self.btn_view_active_peaks)
        peak_row.addWidget(self.btn_active_cluster)
        
        self.spin_peak_prom = QDoubleSpinBox()
        self.spin_peak_prom.setRange(0.1, 100.0)
        self.spin_peak_prom.setValue(3.0)
        self.spin_peak_prom.valueChanged.connect(self._process_and_plot)
        
        self.spin_peak_dist = QSpinBox()
        self.spin_peak_dist.setRange(1, 10000)
        self.spin_peak_dist.setValue(10)
        self.spin_peak_dist.setSuffix(" bins")
        self.spin_peak_dist.valueChanged.connect(self._process_and_plot)
        
        self.spin_peak_width = QSpinBox()
        self.spin_peak_width.setRange(1, 1000)
        self.spin_peak_width.setValue(3)
        self.spin_peak_width.setSuffix(" bins")
        self.spin_peak_width.valueChanged.connect(self._process_and_plot)
        
        peak_layout.addLayout(peak_row)
        peak_layout.addWidget(QLabel("Prominence (dB):"))
        peak_layout.addWidget(self.spin_peak_prom)
        peak_layout.addWidget(QLabel("Min Distance (Separation):"))
        peak_layout.addWidget(self.spin_peak_dist)
        peak_layout.addWidget(QLabel("Min Width (Reject noise spikes):"))
        peak_layout.addWidget(self.spin_peak_width)
        peak_group.setLayout(peak_layout)
        cmd_layout.addWidget(peak_group)

        bulk_group = QGroupBox("Headless Bulk Import")
        bulk_layout = QVBoxLayout()
        
        bulk_btn_row = QHBoxLayout()
        self.btn_bulk_files = QPushButton("Add Files")
        self.btn_bulk_files.clicked.connect(self.add_bulk_files)
        
        self.btn_bulk_dir = QPushButton("Add Directory")
        self.btn_bulk_dir.clicked.connect(self.add_bulk_dir)
        
        self.btn_bulk_clear = QPushButton("Clear Bulk")
        self.btn_bulk_clear.setStyleSheet("color: #FF3333;")
        self.btn_bulk_clear.clicked.connect(self.clear_bulk_data)
        
        bulk_btn_row.addWidget(self.btn_bulk_files)
        bulk_btn_row.addWidget(self.btn_bulk_dir)
        bulk_btn_row.addWidget(self.btn_bulk_clear)
        
        bulk_view_row = QHBoxLayout()
        self.btn_view_bulk_peaks = QPushButton("Bulk Peaks")
        self.btn_view_bulk_peaks.clicked.connect(self.bulk_peak_dialog.show)
        
        self.btn_bulk_cluster = QPushButton("Bulk Clusters")
        self.btn_bulk_cluster.setStyleSheet("background-color: #2a82da; color: white; font-weight: bold;")
        self.btn_bulk_cluster.clicked.connect(self.bulk_cluster_dialog.show)
        
        bulk_view_row.addWidget(self.btn_view_bulk_peaks)
        bulk_view_row.addWidget(self.btn_bulk_cluster)
        
        self.lbl_bulk_status = QLabel("0 bulk files processed.")
        self.lbl_bulk_status.setStyleSheet("color: #888; font-style: italic;")
        
        bulk_layout.addWidget(QLabel("Applies current DSP settings above directly to disk data."))
        bulk_layout.addLayout(bulk_btn_row)
        bulk_layout.addLayout(bulk_view_row)
        bulk_layout.addWidget(self.lbl_bulk_status)
        bulk_group.setLayout(bulk_layout)
        cmd_layout.addWidget(bulk_group)

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, stretch=1)

    def _add_signal_slot(self):
        c_idx = (self.slot_counter - 1) % len(self.color_palette)
        color = QColor(self.color_palette[c_idx])
        
        widget = SignalSlotWidget(self.slot_counter, color)
        widget.data_changed.connect(self._on_slot_data_changed)
        widget.style_changed.connect(self._apply_styles)
        widget.remove_requested.connect(self._remove_signal_slot)
        
        idx = self.sources_layout.count() - 1
        self.sources_layout.insertWidget(idx, widget)
        
        slot_data = {
            'ui': widget,
            'curve': self.plot_widget.plot(autoDownsample=True, downsampleMethod='peak', clipToView=True),
            'minimap_curve': self.minimap_widget.plot(autoDownsample=True),
            'nf_curve': self.plot_widget.plot(autoDownsample=True, clipToView=True),
            'nf_3db_curve': self.plot_widget.plot(autoDownsample=True, clipToView=True),
            'peak_scatter': pg.ScatterPlotItem(size=12, pen=pg.mkPen(None), symbol='t', hoverable=True, hoverSize=16)
        }
        
        self.plot_widget.addItem(slot_data['peak_scatter'])
        self.signal_slots.append(slot_data)
        self.slot_counter += 1
        self._apply_styles()

    def _remove_signal_slot(self, widget):
        for slot in self.signal_slots:
            if slot['ui'] == widget:
                self.plot_widget.removeItem(slot['curve'])
                self.plot_widget.removeItem(slot['nf_curve'])
                self.plot_widget.removeItem(slot['nf_3db_curve'])
                self.plot_widget.removeItem(slot['peak_scatter'])
                self.minimap_widget.removeItem(slot['minimap_curve'])
                
                self.sources_layout.removeWidget(widget)
                widget.deleteLater()
                
                self.signal_slots.remove(slot)
                break
        self._process_and_plot()

    def _on_slot_data_changed(self):
        self.autoscale_x() 
        self._process_and_plot()
    
    def add_bulk_files(self):
        filepaths, _ = QFileDialog.getOpenFileNames(None, "Select Scan Files", "", "Data Files (*.dat)")
        if filepaths:
            self._process_headless_files(filepaths)

    def add_bulk_dir(self):
        dir_path = QFileDialog.getExistingDirectory(None, "Select Directory containing .dat files")
        if dir_path:
            filepaths = [os.path.join(dir_path, f) for f in os.listdir(dir_path) if f.endswith('.dat')]
            self._process_headless_files(filepaths)
            
    def clear_bulk_data(self):
        self.bulk_peaks = []
        self.bulk_file_count = 0
        self.lbl_bulk_status.setText("0 bulk files processed.")
        self.btn_view_bulk_peaks.setText("Bulk Peaks")
        self.bulk_peak_dialog.update_data([])
        self.bulk_cluster_dialog.set_peaks_data([], total_sources=1)

    def _process_headless_files(self, filepaths):
        if not filepaths: return

        filter_type = self.combo_filter.currentText()
        filter_len = self.spin_filter_len.value()
        nf_method = self.combo_nf_method.currentText()
        nf_mhz = self.spin_nf_len.value()
        nf_offset = self.spin_nf_offset.value()
        
        prom = self.spin_peak_prom.value()
        dist = self.spin_peak_dist.value()
        wid = self.spin_peak_width.value()
        
        progress = QProgressDialog("Processing bulk files.", "Cancel", 0, len(filepaths), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0) 

        new_peaks = []
        valid_processed = 0

        for i, fpath in enumerate(filepaths):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            
            data = DatFileParser.parse(fpath)
            if not data or len(data.data_db) == 0: 
                continue
                
            valid_processed += 1
            raw_db = data.data_db
            x_axis = np.linspace(data.start_freq_mhz, data.stop_freq_mhz, len(raw_db))
            
            # Smoothing
            if filter_type == "None" or filter_len < 3:
                filt_db = raw_db
            elif filter_type == "Moving Average":
                filt_db = SpectrumFilters.apply_moving_average(raw_db, filter_len)
            elif filter_type == "Gaussian":
                filt_db = SpectrumFilters.apply_gaussian(raw_db, filter_len)
                
            # Noise Floor
            nf_db = None
            if nf_method != "None":
                bin_hz = data.bin_width_hz if data.bin_width_hz > 0 else 10000
                nf_len = int((nf_mhz * 1_000_000) / bin_hz)
                if nf_len % 2 == 0: nf_len += 1
                nf_len = max(3, nf_len)
                
                if nf_method == "Sliding Average":
                    nf_db = SpectrumFilters.apply_moving_average(filt_db, nf_len)
                elif nf_method == "Sliding Median":
                    nf_db = SpectrumFilters.apply_sliding_median(filt_db, nf_len)
                    
            # Peak Detection
            thresh = None
            if nf_db is not None:
                if self.chk_show_3db.isChecked(): thresh = nf_db + nf_offset
                elif self.chk_show_nf.isChecked(): thresh = nf_db
                    
            peaks, props = SpectrumFilters.find_spectrum_peaks(
                filt_db, height_thresh=thresh, 
                prominence=prom,
                distance=dist,
                width=wid
            )
            
            if len(peaks) > 0:
                px = x_axis[peaks]
                py = filt_db[peaks]
                prominences = props.get('prominences', np.zeros_like(px))
                widths_bins = props.get('widths', np.zeros_like(px))
                
                fname = os.path.basename(fpath)
                for j in range(len(peaks)):
                    new_peaks.append({
                        'source': fname,
                        'freq': px[j],
                        'power': py[j],
                        'prominence': prominences[j],
                        'width_khz': widths_bins[j] * (data.bin_width_hz/1000.0)
                    })

        progress.setValue(len(filepaths))
        
        # Append to static pool
        self.bulk_peaks.extend(new_peaks)
        self.bulk_file_count += valid_processed
        self.lbl_bulk_status.setText(f"{self.bulk_file_count} bulk files processed.")
        
        # Update
        self.bulk_peak_dialog.update_data(self.bulk_peaks)
        self.bulk_cluster_dialog.set_peaks_data(self.bulk_peaks, total_sources=self.bulk_file_count)
        self.btn_view_bulk_peaks.setText(f"Bulk Peaks ({len(self.bulk_peaks)})")

    def _on_filter_len_changed(self, val):
        if val % 2 == 0:
            self.spin_filter_len.blockSignals(True)
            self.spin_filter_len.setValue(val + 1)
            self.spin_filter_len.blockSignals(False)
        self._process_and_plot()

    def _on_nf_checkbox_changed(self, state=None):
        valid_method = self.combo_nf_method.currentText() != "None"
        show_nf = valid_method and self.chk_show_nf.isChecked()
        show_3db = valid_method and self.chk_show_3db.isChecked()
        
        for slot in self.signal_slots:
            slot['nf_curve'].setVisible(show_nf)
            slot['nf_3db_curve'].setVisible(show_3db)
            
        if self.chk_enable_peaks.isChecked():
            self._process_and_plot()

    def _process_and_plot(self):
        active_peaks_table = []
        
        filter_type = self.combo_filter.currentText()
        filter_len = self.spin_filter_len.value()
        
        nf_method = self.combo_nf_method.currentText()
        nf_mhz = self.spin_nf_len.value()
        nf_offset = self.spin_nf_offset.value()

        pen_nf = pg.mkPen(color=self.nf_color, width=2, style=Qt.DashLine)
        pen_3db = pg.mkPen(color=self.nf_3db_color, width=2, style=Qt.DashLine)

        for slot in self.signal_slots:
            ui = slot['ui']
            if not ui.parsed_data: continue 

            raw_db = ui.parsed_data.data_db
            x_axis = ui.x_axis
            
            # Smoothing
            if filter_type == "None":
                filt_db = raw_db
            elif filter_type == "Moving Average":
                filt_db = SpectrumFilters.apply_moving_average(raw_db, filter_len)
            elif filter_type == "Gaussian":
                filt_db = SpectrumFilters.apply_gaussian(raw_db, filter_len)

            slot['filtered_data_db'] = filt_db

            # Minimap Static Decimation
            if len(filt_db) > 0:
                mini_step = max(1, len(filt_db) // 5000)
                slot['minimap_curve'].setData(x_axis[::mini_step], filt_db[::mini_step])

            ui.noise_floor = float(np.min(filt_db))

            # Noise Floor
            nf_db = None
            if nf_method != "None":
                bin_hz = ui.parsed_data.bin_width_hz if ui.parsed_data.bin_width_hz > 0 else 10000
                nf_len = int((nf_mhz * 1_000_000) / bin_hz)
                if nf_len % 2 == 0: nf_len += 1
                nf_len = max(3, nf_len)
                
                if nf_method == "Sliding Average":
                    nf_db = SpectrumFilters.apply_moving_average(filt_db, nf_len)
                elif nf_method == "Sliding Median":
                    nf_db = SpectrumFilters.apply_sliding_median(filt_db, nf_len)
                    
            slot['nf_data_db'] = nf_db
            
            if nf_db is not None:
                slot['nf_curve'].setPen(pen_nf)
                slot['nf_3db_curve'].setPen(pen_3db)

            # Peak Detection
            if self.chk_enable_peaks.isChecked():
                thresh = None
                if nf_db is not None:
                    if self.chk_show_3db.isChecked(): thresh = nf_db + nf_offset
                    elif self.chk_show_nf.isChecked(): thresh = nf_db
                        
                prom = self.spin_peak_prom.value()
                dist = self.spin_peak_dist.value()
                wid = self.spin_peak_width.value()
                
                peaks, props = SpectrumFilters.find_spectrum_peaks(
                    filt_db, height_thresh=thresh, 
                    prominence=prom,
                    distance=dist,
                    width=wid
                )
                
                if len(peaks) > 0:
                    px = x_axis[peaks]
                    py = filt_db[peaks]
                    slot['peak_scatter'].setData(px, py)
                    
                    for i in range(len(peaks)):
                        active_peaks_table.append({
                            'source': ui.lbl_filename.text(),
                            'freq': px[i],
                            'power': py[i],
                            'prominence': props.get('prominences', [0]*len(px))[i],
                            'width_khz': props.get('widths', [0]*len(px))[i] * (ui.parsed_data.bin_width_hz/1000.0)
                        })
                else:
                    slot['peak_scatter'].clear()
            else:
                slot['peak_scatter'].clear()

        valid_method = self.combo_nf_method.currentText() != "None"
        show_nf = valid_method and self.chk_show_nf.isChecked()
        show_3db = valid_method and self.chk_show_3db.isChecked()
        
        for slot in self.signal_slots:
            slot['nf_curve'].setVisible(show_nf)
            slot['nf_3db_curve'].setVisible(show_3db)
            
        self._apply_styles()
        
        # Push peaks
        valid_slots_count = sum(1 for s in self.signal_slots if s['ui'].parsed_data)
        self.active_peak_dialog.update_data(active_peaks_table)
        self.active_cluster_dialog.set_peaks_data(active_peaks_table, total_sources=valid_slots_count)
        self.btn_view_active_peaks.setText(f"Active Peaks ({len(active_peaks_table)})")

        self.refresh_plot_data()

    def _apply_styles(self):
        for slot in self.signal_slots:
            ui = slot['ui']
            
            pen_color = QColor(ui.color)
            pen_color.setAlpha(ui.opacity)
            slot['curve'].setPen(pen_color)
            
            fill = QColor(ui.color)
            fill.setAlpha(int(ui.opacity * 0.3))
            slot['curve'].setFillLevel(ui.noise_floor - 10.0)
            slot['curve'].setBrush(fill)
            
            peak_brush = QColor(ui.color)
            peak_brush.setAlpha(ui.opacity)
            slot['peak_scatter'].setBrush(pg.mkBrush(peak_brush))

    def autoscale_x(self):
        min_x, max_x = None, None
        for slot in self.signal_slots:
            if slot['ui'].parsed_data:
                d = slot['ui'].parsed_data
                min_x = d.start_freq_mhz if min_x is None else min(min_x, d.start_freq_mhz)
                max_x = d.stop_freq_mhz if max_x is None else max(max_x, d.stop_freq_mhz)
        
        if min_x is not None and max_x is not None:
            self.region.setBounds([min_x, max_x])
            self.region.setRegion([min_x, max_x])
            self.plot_widget.autoRange()

    def autoscale_y(self):
        x_min, x_max = self.plot_widget.viewRange()[0]
        y_min, y_max = None, None
        
        for slot in self.signal_slots:
            ui = slot['ui']
            if not ui.parsed_data or ui.x_axis is None: continue
            
            filt_db = slot.get('filtered_data_db')
            if filt_db is None: continue
            
            mask = (ui.x_axis >= x_min) & (ui.x_axis <= x_max)
            vis = filt_db[mask]
            
            if len(vis) > 0:
                y_min = float(np.min(vis)) if y_min is None else min(y_min, float(np.min(vis)))
                y_max = float(np.max(vis)) if y_max is None else max(y_max, float(np.max(vis)))
                
        if y_min is not None and y_max is not None:
            self.plot_widget.setYRange(y_min - 3, y_max + 5, padding=0)

    def on_region_changed(self, region):
        rgn = region.getRegion()
        self.plot_widget.blockSignals(True)
        self.plot_widget.setXRange(*rgn, padding=0)
        self.plot_widget.blockSignals(False)
        self.update_timer.start(100)

    def on_range_changed(self, window, viewRange):
        rgn = viewRange[0]
        self.region.blockSignals(True)
        self.region.setRegion(rgn)
        self.region.blockSignals(False)
        self.update_timer.start(100)

    def refresh_plot_data(self):
        view_range = self.plot_widget.viewRange()[0]
        min_f, max_f = view_range[0], view_range[1]
        
        pad_f = (max_f - min_f) * 0.15
        min_f_padded = min_f - pad_f
        max_f_padded = max_f + pad_f
        
        max_points_visible = 0
        nf_offset = self.spin_nf_offset.value()

        for slot in self.signal_slots:
            ui = slot['ui']
            if not ui.parsed_data or ui.x_axis is None: continue
            
            filt_db = slot.get('filtered_data_db')
            if filt_db is None: continue
                
            i_start = np.searchsorted(ui.x_axis, min_f_padded, side='left')
            i_stop = np.searchsorted(ui.x_axis, max_f_padded, side='right')
            
            i_start = max(0, i_start)
            i_stop = min(len(ui.x_axis), i_stop)
            
            if i_stop <= i_start: continue
            
            view_x = ui.x_axis[i_start:i_stop]
            view_y = filt_db[i_start:i_stop]
            
            num_points = len(view_x)
            max_points_visible = max(max_points_visible, num_points)
            
            if num_points > self.spin_plot_thresh.value():
                slot['curve'].setDownsampling(auto=True, method='peak')
                slot['nf_curve'].setDownsampling(auto=True, method='peak')
                slot['nf_3db_curve'].setDownsampling(auto=True, method='peak')
            else:
                slot['curve'].setDownsampling(auto=False)
                slot['nf_curve'].setDownsampling(auto=False)
                slot['nf_3db_curve'].setDownsampling(auto=False)
                
            slot['curve'].setData(view_x, view_y)
            
            nf_db = slot.get('nf_data_db')
            if nf_db is not None:
                view_nf = nf_db[i_start:i_stop]
                slot['nf_curve'].setData(view_x, view_nf)
                slot['nf_3db_curve'].setData(view_x, view_nf + nf_offset)
                
        if max_points_visible > self.spin_plot_thresh.value():
            self.lbl_active_points.setText(f"Max Visible Pts: {max_points_visible:,}  [Downsampled]")
        else:
            self.lbl_active_points.setText(f"Max Visible Pts: {max_points_visible:,}  [1:1]")

    def choose_nf_color(self):
        c = QColorDialog.getColor(self.nf_color, self, "Base Noise Floor Color")
        if c.isValid():
            self.nf_color = c
            self._process_and_plot()
            
    def choose_3db_color(self):
        c = QColorDialog.getColor(self.nf_3db_color, self, "Offset Threshold Color")
        if c.isValid():
            self.nf_3db_color = c
            self._process_and_plot()

    def update_theme(self, is_dark: bool):
        bg = '#191919' if is_dark else '#F0F0F0'
        fg = 'w' if is_dark else 'k'
        
        self.plot_widget.setBackground(bg)
        self.minimap_widget.setBackground(bg)
        
        self.active_cluster_dialog.plot_widget.setBackground(bg)
        self.active_cluster_dialog.minimap_widget.setBackground(bg)
        self.bulk_cluster_dialog.plot_widget.setBackground(bg)
        self.bulk_cluster_dialog.minimap_widget.setBackground(bg)
        
        plots = [
            self.plot_widget, self.minimap_widget, 
            self.active_cluster_dialog.plot_widget, self.active_cluster_dialog.minimap_widget,
            self.bulk_cluster_dialog.plot_widget, self.bulk_cluster_dialog.minimap_widget
        ]
        
        for plot in plots:
            plot.getAxis('bottom').setPen(fg)
            plot.getAxis('left').setPen(fg)
            plot.getAxis('bottom').setTextPen(fg)
            plot.getAxis('left').setTextPen(fg)
            
        for slot in self.signal_slots:
            slot['minimap_curve'].setPen(pg.mkPen(color=fg, width=1, style=Qt.SolidLine))

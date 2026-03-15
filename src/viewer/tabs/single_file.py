import os
import csv
import pyqtgraph as pg
import numpy as np
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFileDialog, QGroupBox, QColorDialog, QSlider, 
                             QMessageBox, QComboBox, QSpinBox, QCheckBox, QDoubleSpinBox,
                             QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
                             QScrollArea, QFrame)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor

# Import our parser and DSP utils
from viewer.data_parser import DatFileParser
from viewer.dsp_utils import SpectrumFilters

class NumericTableItem(QTableWidgetItem):
    def __init__(self, value, format_str="{:.2f}"):
        super().__init__(format_str.format(value))
        self.value = float(value)
        
    def __lt__(self, other):
        if isinstance(other, NumericTableItem):
            return self.value < other.value
        return super().__lt__(other)

class PeakTableDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detected Signal Peaks")
        self.resize(500, 600)
        self.current_export_path = ""
        
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Frequency (MHz)", "Power (dB)", "Prominence (dB)", "Est. Width (kHz)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSortingEnabled(True)
        
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        self.btn_export = QPushButton("Export to CSV")
        self.btn_export.clicked.connect(self.export_csv)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_export)
        layout.addLayout(btn_layout)
        
    def set_export_path(self, default_path):
        self.current_export_path = default_path

    def update_data(self, peak_data):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(peak_data))
        
        for row, peak in enumerate(peak_data):
            self.table.setItem(row, 0, NumericTableItem(peak['freq'], "{:.3f}"))
            self.table.setItem(row, 1, NumericTableItem(peak['power'], "{:.2f}"))
            self.table.setItem(row, 2, NumericTableItem(peak['prominence'], "{:.2f}"))
            self.table.setItem(row, 3, NumericTableItem(peak['width_khz'], "{:.1f}"))
            
        self.table.setSortingEnabled(True)
        
    def export_csv(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "Export", "No peak data available to export.")
            return
            
        path, _ = QFileDialog.getSaveFileName(self, "Export Peaks CSV", self.current_export_path, "CSV Files (*.csv)")
        if path:
            try:
                with open(path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    # Write Header
                    headers = [self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())]
                    writer.writerow(headers)
                    # Write Data
                    for row in range(self.table.rowCount()):
                        row_data = []
                        for col in range(self.table.columnCount()):
                            item = self.table.item(row, col)
                            row_data.append(item.text() if item else "")
                        writer.writerow(row_data)
                QMessageBox.information(self, "Export Successful", f"Successfully saved peaks to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to save CSV:\n{e}")

class SingleFileTab(QWidget):
    def __init__(self):
        super().__init__()
        
        # State variables
        self.current_color = QColor(15, 235, 15) # Default Green
        self.fill_opacity = 50 # 0-255
        self.noise_floor = -100.0 # Will dynamically update when file loads
        
        self.nf_color = QColor('#FFA500') # Orange Default
        self.nf_3db_color = QColor('#FF3333') # Red Default
        self.peak_color = QColor(255, 0, 0) # Red Default for Peaks
        
        # Data persistence for auto-scaling and filtering
        self.current_x_axis = None
        self.current_data_db = None
        self.filtered_data_db = None 
        self.nf_data_db = None       
        self.bin_width_hz = 10000    
        
        # Debouncing timer for heavy array slicing
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.refresh_plot_data)
        
        # Popout Dialog
        self.peak_dialog = PeakTableDialog(self)
        
        self._init_ui()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        plot_layout = QVBoxLayout()
        
        pg.setConfigOption('background', '#191919')
        pg.setConfigOption('foreground', 'w')
        
        # Main Plot
        self.plot_widget = pg.PlotWidget(title="Spectrum Max-Hold")
        self.plot_widget.setLabel('left', 'Power', units='dB')
        self.plot_widget.setLabel('bottom', 'Frequency', units='MHz')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        self.main_curve = self.plot_widget.plot(
            pen=self.current_color,
            autoDownsample=True,     
            downsampleMethod='peak', 
            clipToView=True          
        )
        
        # Noise Floor Curves (hidden by default)
        pen_nf = pg.mkPen(color=self.nf_color, width=2, style=Qt.DashLine) 
        pen_3db = pg.mkPen(color=self.nf_3db_color, width=2, style=Qt.DashLine) 
        
        self.nf_curve = self.plot_widget.plot(pen=pen_nf, autoDownsample=True, clipToView=True)
        self.nf_3db_curve = self.plot_widget.plot(pen=pen_3db, autoDownsample=True, clipToView=True)
        self.nf_curve.setVisible(False)
        self.nf_3db_curve.setVisible(False)
        
        # Peak Scatter Plot
        self.peak_scatter = pg.ScatterPlotItem(
            size=12, 
            pen=pg.mkPen(None), 
            brush=pg.mkBrush(self.peak_color), 
            symbol='t', 
            hoverable=True,
            hoverSymbol='t',
            hoverSize=16
        )
        self.plot_widget.addItem(self.peak_scatter)

        # Minimap (Bottom Plot)
        self.minimap_widget = pg.PlotWidget()
        self.minimap_widget.setMaximumHeight(150)
        self.minimap_widget.setLabel('bottom', 'Frequency Overview', units='MHz')
        self.minimap_widget.hideAxis('left')
        
        self.minimap_curve = self.minimap_widget.plot(pen=pg.mkPen(color='w', width=1, style=Qt.SolidLine), autoDownsample=True)
        
        self.region = pg.LinearRegionItem(
            pen=pg.mkPen(color='w', width=3),
            hoverPen=pg.mkPen(color='#4CAF50', width=5)
        )
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
        
        scroll_content = QWidget()
        cmd_layout = QVBoxLayout(scroll_content)
        cmd_layout.setAlignment(Qt.AlignTop)

        file_group = QGroupBox("Data Source")
        f_layout = QVBoxLayout()
        self.btn_load = QPushButton("Load .dat File")
        self.btn_load.clicked.connect(self.load_file)
        
        self.lbl_filename = QLabel("No file loaded")
        self.lbl_filename.setWordWrap(True)
        self.lbl_filename.setStyleSheet("font-weight: bold; color: #4CAF50;")
        
        self.lbl_meta = QLabel("Span: --\nTimestamp: --")
        
        f_layout.addWidget(self.btn_load)
        f_layout.addWidget(self.lbl_filename)
        f_layout.addWidget(self.lbl_meta)
        file_group.setLayout(f_layout)
        cmd_layout.addWidget(file_group)

        appearance_group = QGroupBox("Appearance and View")
        a_layout = QVBoxLayout()
        
        self.lbl_active_points = QLabel("Visible Points: --")
        self.lbl_active_points.setWordWrap(True)
        self.lbl_active_points.setStyleSheet("font-size: 11px; color: #888; font-weight: bold;")
        a_layout.addWidget(self.lbl_active_points)
        
        row_thresh = QHBoxLayout()
        row_thresh.addWidget(QLabel("1:1 Render Threshold:"))
        self.spin_plot_thresh = QSpinBox()
        self.spin_plot_thresh.setRange(1000, 5000000)
        self.spin_plot_thresh.setSingleStep(10000)
        self.spin_plot_thresh.setValue(50000)
        self.spin_plot_thresh.setToolTip("Max points drawn 1:1 before peak-downsampling activates.")
        self.spin_plot_thresh.valueChanged.connect(self.refresh_plot_data)
        row_thresh.addWidget(self.spin_plot_thresh)
        a_layout.addLayout(row_thresh)
        
        self.btn_autoscale_y = QPushButton("Auto Scale Y-Axis (Current View)")
        self.btn_autoscale_y.clicked.connect(self.autoscale_y)
        
        self.btn_color = QPushButton("Change Line Color")
        self.btn_color.clicked.connect(self.choose_color)
        
        a_layout.addWidget(QLabel("Fill Opacity:"))
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(0, 255)
        self.slider_opacity.setValue(self.fill_opacity)
        self.slider_opacity.valueChanged.connect(self.change_opacity)
        
        a_layout.addWidget(self.btn_autoscale_y)
        a_layout.addWidget(self.btn_color)
        a_layout.addWidget(self.slider_opacity)
        appearance_group.setLayout(a_layout)
        cmd_layout.addWidget(appearance_group)

        dsp_group = QGroupBox("Signal Smoothing")
        dsp_layout = QVBoxLayout()
        
        self.combo_filter = QComboBox()
        self.combo_filter.addItems(["None", "Moving Average", "Gaussian"])
        self.combo_filter.currentIndexChanged.connect(self._process_and_plot)
        
        self.spin_filter_len = QSpinBox()
        self.spin_filter_len.setRange(3, 999)
        self.spin_filter_len.setSingleStep(2)
        self.spin_filter_len.setValue(5)
        self.spin_filter_len.setSuffix(" bins")
        self.spin_filter_len.valueChanged.connect(self._on_filter_len_changed)
        
        dsp_layout.addWidget(QLabel("Smoothing Filter:"))
        dsp_layout.addWidget(self.combo_filter)
        dsp_layout.addWidget(QLabel("Filter Length (Odd):"))
        dsp_layout.addWidget(self.spin_filter_len)
        dsp_group.setLayout(dsp_layout)
        cmd_layout.addWidget(dsp_group)

        nf_group = QGroupBox("Noise Floor Estimation")
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
        self.chk_show_nf = QCheckBox("Show Noise Floor Baseline")
        self.chk_show_nf.stateChanged.connect(self._on_nf_checkbox_changed)
        self.btn_nf_color = QPushButton("Color")
        self.btn_nf_color.setMaximumWidth(60)
        self.btn_nf_color.clicked.connect(self.choose_nf_color)
        nf_row_layout.addWidget(self.chk_show_nf)
        nf_row_layout.addWidget(self.btn_nf_color)
        
        db3_row_layout = QHBoxLayout()
        self.chk_show_3db = QCheckBox("Show Offset Threshold")
        self.chk_show_3db.stateChanged.connect(self._on_nf_checkbox_changed)
        
        self.spin_nf_offset = QDoubleSpinBox()
        self.spin_nf_offset.setRange(0.5, 100.0)
        self.spin_nf_offset.setSingleStep(0.5)
        self.spin_nf_offset.setValue(3.0)
        self.spin_nf_offset.setSuffix(" dB")
        self.spin_nf_offset.valueChanged.connect(self._process_and_plot)
        
        self.btn_3db_color = QPushButton("Color")
        self.btn_3db_color.setMaximumWidth(60)
        self.btn_3db_color.clicked.connect(self.choose_3db_color)
        
        db3_row_layout.addWidget(self.chk_show_3db)
        db3_row_layout.addWidget(self.spin_nf_offset)
        db3_row_layout.addWidget(self.btn_3db_color)
        
        nf_layout.addWidget(QLabel("Estimation Method:"))
        nf_layout.addWidget(self.combo_nf_method)
        nf_layout.addWidget(QLabel("Window Size:"))
        nf_layout.addWidget(self.spin_nf_len)
        nf_layout.addLayout(nf_row_layout)
        nf_layout.addLayout(db3_row_layout)
        nf_group.setLayout(nf_layout)
        cmd_layout.addWidget(nf_group)

        peak_group = QGroupBox("Peak Detection")
        peak_layout = QVBoxLayout()
        
        peak_row = QHBoxLayout()
        self.chk_enable_peaks = QCheckBox("Enable Peak Detection")
        self.chk_enable_peaks.stateChanged.connect(self._process_and_plot)
        
        self.btn_peak_color = QPushButton("Color")
        self.btn_peak_color.setMaximumWidth(50)
        self.btn_peak_color.clicked.connect(self.choose_peak_color)
        
        self.btn_view_table = QPushButton("View Table")
        self.btn_view_table.clicked.connect(self.peak_dialog.show)
        
        peak_row.addWidget(self.chk_enable_peaks)
        peak_row.addWidget(self.btn_peak_color)
        peak_row.addWidget(self.btn_view_table)
        
        self.spin_peak_prom = QDoubleSpinBox()
        self.spin_peak_prom.setRange(0.1, 100.0)
        self.spin_peak_prom.setSingleStep(0.5)
        self.spin_peak_prom.setValue(3.0)
        self.spin_peak_prom.setSuffix(" dB")
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
        peak_layout.addWidget(QLabel("Prominence (Height above valleys):"))
        peak_layout.addWidget(self.spin_peak_prom)
        peak_layout.addWidget(QLabel("Min Distance (Separation):"))
        peak_layout.addWidget(self.spin_peak_dist)
        peak_layout.addWidget(QLabel("Min Width (Reject noise spikes):"))
        peak_layout.addWidget(self.spin_peak_width)
        peak_group.setLayout(peak_layout)
        cmd_layout.addWidget(peak_group)

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, stretch=1)
        self._apply_plot_style()

    def _on_filter_len_changed(self, val):
        if val % 2 == 0:
            self.spin_filter_len.blockSignals(True)
            self.spin_filter_len.setValue(val + 1)
            self.spin_filter_len.blockSignals(False)
        self._process_and_plot()

    def _on_nf_checkbox_changed(self, state=None):
        valid_method = self.combo_nf_method.currentText() != "None"
        self.nf_curve.setVisible(valid_method and self.chk_show_nf.isChecked())
        self.nf_3db_curve.setVisible(valid_method and self.chk_show_3db.isChecked())
        
        if self.chk_enable_peaks.isChecked():
            self._process_and_plot()

    def _process_and_plot(self):
        """Applies filters, calculates noise floors, detects peaks, and updates plots/tables."""
        if self.current_data_db is None or self.current_x_axis is None:
            return

        # Apply Primary Smoothing Filter
        filter_type = self.combo_filter.currentText()
        window_len = self.spin_filter_len.value()

        if filter_type == "None" or window_len < 3:
            self.filtered_data_db = self.current_data_db
        elif filter_type == "Moving Average":
            self.filtered_data_db = SpectrumFilters.apply_moving_average(self.current_data_db, window_len)
        elif filter_type == "Gaussian":
            self.filtered_data_db = SpectrumFilters.apply_gaussian(self.current_data_db, window_len)

        # Update Minimap with static decimation
        if len(self.filtered_data_db) > 0:
            mini_step = max(1, len(self.filtered_data_db) // 5000)
            mini_y = self.filtered_data_db[::mini_step]
            mini_x = self.current_x_axis[::mini_step]
            self.minimap_curve.setData(mini_x, mini_y)
        
        # Calculate Noise Floor 
        nf_method = self.combo_nf_method.currentText()
        span_mhz = self.spin_nf_len.value()
        
        span_hz = span_mhz * 1_000_000
        bin_hz = self.bin_width_hz if self.bin_width_hz > 0 else 10000
        nf_len = int(span_hz / bin_hz)
        if nf_len % 2 == 0:
            nf_len += 1
        nf_len = max(3, nf_len) 

        if nf_method == "None":
            self.nf_data_db = None
        elif nf_method == "Sliding Average":
            self.nf_data_db = SpectrumFilters.apply_moving_average(self.filtered_data_db, nf_len)
        elif nf_method == "Sliding Median":
            self.nf_data_db = SpectrumFilters.apply_sliding_median(self.filtered_data_db, nf_len)

        # Process Noise Floor bounds
        nf_offset = self.spin_nf_offset.value()

        valid_method = self.combo_nf_method.currentText() != "None"
        self.nf_curve.setVisible(valid_method and self.chk_show_nf.isChecked())
        self.nf_3db_curve.setVisible(valid_method and self.chk_show_3db.isChecked())

        # Peak Detection
        if self.chk_enable_peaks.isChecked():
            thresh = None
            if self.nf_data_db is not None:
                if self.chk_show_3db.isChecked():
                    thresh = self.nf_data_db + nf_offset
                elif self.chk_show_nf.isChecked():
                    thresh = self.nf_data_db
                    
            prom = self.spin_peak_prom.value()
            dist = self.spin_peak_dist.value()
            wid = self.spin_peak_width.value()
            
            peak_indices, props = SpectrumFilters.find_spectrum_peaks(
                self.filtered_data_db, 
                height_thresh=thresh, 
                prominence=prom, 
                distance=dist, 
                width=wid
            )
            
            if len(peak_indices) > 0:
                peak_x = self.current_x_axis[peak_indices]
                peak_y = self.filtered_data_db[peak_indices]
                
                # Plot markers
                self.peak_scatter.setData(peak_x, peak_y)
                
                # Assemble tabular data
                prominences = props.get('prominences', np.zeros_like(peak_x))
                widths_bins = props.get('widths', np.zeros_like(peak_x))
                
                table_data = []
                for i in range(len(peak_indices)):
                    table_data.append({
                        'freq': peak_x[i],
                        'power': peak_y[i],
                        'prominence': prominences[i],
                        'width_khz': widths_bins[i] * (self.bin_width_hz / 1000.0)
                    })
                
                self.peak_dialog.update_data(table_data)
                self.btn_view_table.setText(f"View Table ({len(peak_indices)})")
            else:
                self.peak_scatter.clear()
                self.peak_dialog.update_data([])
                self.btn_view_table.setText("View Table (0)")
        else:
            self.peak_scatter.clear()
            self.peak_dialog.update_data([])
            self.btn_view_table.setText("View Table")

        # Update dynamic fill bounds
        self.noise_floor = float(np.min(self.filtered_data_db))
        self._apply_plot_style()
        
        # Trigger an immediate viewport render update
        self.refresh_plot_data()

    def on_region_changed(self, region):
        # Dragging the minimap instantly syncs the main plot, triggers debounce timer
        rgn = region.getRegion()
        self.plot_widget.blockSignals(True)
        self.plot_widget.setXRange(*rgn, padding=0)
        self.plot_widget.blockSignals(False)
        self.update_timer.start(100)

    def on_range_changed(self, window, viewRange):
        # Panning/zooming the main plot instantly syncs the minimap, triggers debounce timer
        rgn = viewRange[0]
        self.region.blockSignals(True)
        self.region.setRegion(rgn)
        self.region.blockSignals(False)
        self.update_timer.start(100)

    def refresh_plot_data(self):
        if self.current_x_axis is None or self.filtered_data_db is None:
            return

        total_points = len(self.current_x_axis)
        view_range = self.plot_widget.viewRange()[0]
        min_f, max_f = view_range[0], view_range[1]

        pad_f = (max_f - min_f) * 0.25
        min_f_padded = min_f - pad_f
        max_f_padded = max_f + pad_f

        # Array slicing (using searchsorted)
        i_start = np.searchsorted(self.current_x_axis, min_f_padded, side='left')
        i_stop = np.searchsorted(self.current_x_axis, max_f_padded, side='right')

        i_start = max(0, i_start)
        i_stop = min(total_points, i_stop)

        if i_stop <= i_start:
            return

        view_x = self.current_x_axis[i_start:i_stop]
        view_y = self.filtered_data_db[i_start:i_stop]

        # Dynamic downsampling
        num_points = len(view_x)
        if num_points > self.spin_plot_thresh.value():
            self.main_curve.setDownsampling(auto=True, method='peak')
            self.nf_curve.setDownsampling(auto=True, method='peak')
            self.nf_3db_curve.setDownsampling(auto=True, method='peak')
            self.lbl_active_points.setText(f"Visible Points: {num_points:,}  [Downsampled]")
        else:
            self.main_curve.setDownsampling(auto=False)
            self.nf_curve.setDownsampling(auto=False)
            self.nf_3db_curve.setDownsampling(auto=False)
            self.lbl_active_points.setText(f"Visible Points: {num_points:,}  [1:1]")

        self.main_curve.setData(view_x, view_y)

        # Noise floor data
        if self.nf_data_db is not None:
            view_nf = self.nf_data_db[i_start:i_stop]
            self.nf_curve.setData(view_x, view_nf)
            self.nf_3db_curve.setData(view_x, view_nf + self.spin_nf_offset.value())

    def autoscale_y(self):
        if self.current_x_axis is None or self.filtered_data_db is None:
            return
            
        x_min, x_max = self.plot_widget.viewRange()[0]
        mask = (self.current_x_axis >= x_min) & (self.current_x_axis <= x_max)
        visible_data = self.filtered_data_db[mask] 
        
        if len(visible_data) > 0:
            y_min = float(np.min(visible_data))
            y_max = float(np.max(visible_data))
            self.plot_widget.setYRange(y_min - 3, y_max + 5, padding=0)

    def choose_color(self):
        color = QColorDialog.getColor(self.current_color, self, "Select Plot Color")
        if color.isValid():
            self.current_color = color
            self._apply_plot_style()

    def choose_nf_color(self):
        color = QColorDialog.getColor(self.nf_color, self, "Select Noise Floor Baseline Color")
        if color.isValid():
            self.nf_color = color
            self.nf_curve.setPen(pg.mkPen(color=self.nf_color, width=2, style=Qt.DashLine))
            
    def choose_3db_color(self):
        color = QColorDialog.getColor(self.nf_3db_color, self, "Select Offset Threshold Color")
        if color.isValid():
            self.nf_3db_color = color
            self.nf_3db_curve.setPen(pg.mkPen(color=self.nf_3db_color, width=2, style=Qt.DashLine))

    def choose_peak_color(self):
        color = QColorDialog.getColor(self.peak_color, self, "Select Peak Marker Color")
        if color.isValid():
            self.peak_color = color
            self.peak_scatter.setBrush(pg.mkBrush(self.peak_color))

    def change_opacity(self, value):
        self.fill_opacity = value
        self._apply_plot_style()

    def _apply_plot_style(self):
        self.main_curve.setPen(self.current_color)
        fill_color = QColor(self.current_color)
        fill_color.setAlpha(self.fill_opacity)
        self.main_curve.setFillLevel(self.noise_floor - 10.0) 
        self.main_curve.setBrush(fill_color)

    def update_theme(self, is_dark: bool):
        bg = '#191919' if is_dark else '#E5E5E5'
        fg = 'w' if is_dark else 'k'
        
        self.plot_widget.setBackground(bg)
        self.minimap_widget.setBackground(bg)
        
        for plot in [self.plot_widget, self.minimap_widget]:
            plot.getAxis('bottom').setPen(fg)
            plot.getAxis('left').setPen(fg)
            plot.getAxis('bottom').setTextPen(fg)
            plot.getAxis('left').setTextPen(fg)
            
        self.minimap_curve.setPen(pg.mkPen(color=fg, width=1, style=Qt.SolidLine))

    def load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Scan File", "", "Data Files (*.dat)")
        if not file_path:
            return

        parsed_data = DatFileParser.parse(file_path)
        
        if not parsed_data:
            QMessageBox.critical(self, "Error", "Failed to parse .dat file. Check logs.")
            return

        # Prepare default CSV export name for the Peak Table Dialog
        base_path, _ = os.path.splitext(file_path)
        self.peak_dialog.set_export_path(f"{base_path}_peaks.csv")

        self.lbl_filename.setText(os.path.basename(file_path))
        formatted_time = parsed_data.timestamp.replace('T', ' ')[:19] 
        self.lbl_meta.setText(f"Span: {parsed_data.start_freq_mhz}M - {parsed_data.stop_freq_mhz}M\nTime: {formatted_time}")

        x_axis = np.linspace(
            parsed_data.start_freq_mhz, 
            parsed_data.stop_freq_mhz, 
            len(parsed_data.data_db)
        )

        self.current_x_axis = x_axis
        self.current_data_db = parsed_data.data_db
        self.bin_width_hz = parsed_data.bin_width_hz
        
        self._process_and_plot()

        self.region.setBounds([parsed_data.start_freq_mhz, parsed_data.stop_freq_mhz])
        self.region.setRegion([parsed_data.start_freq_mhz, parsed_data.stop_freq_mhz])
        self.plot_widget.autoRange()

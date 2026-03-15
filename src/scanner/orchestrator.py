from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
import time
import datetime
import logging
from enum import Enum
import numpy as np

from scanner.max_hold import MaxHoldTracker
from scanner.file_io import AtomicSaver
from scanner.radio.base import RadioBackend

class State(Enum):
    IDLE = 1
    RUNNING = 2
    ERROR = 3
    STOPPING = 4

class ScanOrchestrator(QThread):
    status_msg = pyqtSignal(str)
    scan_started = pyqtSignal()
    scan_stopped = pyqtSignal()
    error_occurred = pyqtSignal(str)
    hardware_reset_required = pyqtSignal()
    data_updated = pyqtSignal(np.ndarray, object) 

    def __init__(self, radio_backend: RadioBackend, parent=None):
        super().__init__(parent)
        self.radio = radio_backend
        self.state = State.IDLE
        self.logger = logging.getLogger(__name__)
        
        self.config = {}
        self.is_running = False
        self._mutex = QMutex()

        self.watchdog_timeout = 5.0
        self.save_interval = 10.0
        
        self.subscan_count = 0
        self.tracker = None
        self.saver = None
        self.current_plan = None
        self._stopped_early = False

        # Metrics for logging
        self.chunk_counter = 0
        self.last_log_time = 0

    def configure(self, config_dict: dict):
        with QMutexLocker(self._mutex):
            self.config = config_dict
            self.subscan_count = 0
            self._stopped_early = False

    def stop(self, early_termination=True):
        with QMutexLocker(self._mutex):
            if self.state == State.ERROR:
                self.logger.error(f"Stopping scan due to error state.")
                return
            self.is_running = False
            self.state = State.STOPPING
            self._stopped_early = early_termination
        self.logger.info(f"Stopping scan. (Early Termination: {early_termination})")
        self.status_msg.emit("Stopping scan.")

    def run(self):
        self.is_running = True
        self.logger.info("Hardware Calibrating.")
        self.status_msg.emit("Hardware Calibrating.")

        # Start the Radio and receive the mapped plan
        self.current_plan = self.radio.start_scan(self.config)
        
        if not self.current_plan:
            self.error_occurred.emit("Failed to initialize or calibrate radio.")
            self.state = State.ERROR
            return

        # Initialize DSP and IO based on the Plan
        subscan_enabled = self.config.get('subscan_enabled', False)
        self.tracker = MaxHoldTracker(self.current_plan.total_bins, subscan_enabled)
        self.saver = AtomicSaver(self.config.get('save_dir'), self.config.get('base_filename'))

        # Transition to Running
        self.state = State.RUNNING
        self.scan_started.emit()
        run_msg = f"Running [{self.current_plan.actual_start_mhz}M - {self.current_plan.actual_stop_mhz}M]"
        self.logger.info(run_msg)
        self.status_msg.emit(run_msg)

        current_time = time.time()
        start_time = current_time
        last_data_time = current_time
        last_save_time = current_time
        last_subscan_time = current_time
        
        self.last_log_time = current_time
        self.chunk_counter = 0
        
        subscan_interval_sec = self.config.get('subscan_interval_min', 30) * 60.0
        scan_duration_sec = self.config.get('scan_duration_sec', 0)
        next_milestone_pct = 20

        # Core Acquisition Loop
        while self.is_running:
            chunk = self.radio.read_chunk(timeout=1.0)
            current_time = time.time()

            if chunk:
                # Any chunk (data or heartbeat) resets the Watchdog
                last_data_time = current_time
                
                if chunk.start_index != -1:
                    # Valid mapped chunk, pass to DSP layer
                    self.tracker.update(chunk)
                    self.chunk_counter += 1
            else:
                if current_time - last_data_time > self.watchdog_timeout:
                    self.logger.warning("Watchdog triggered.")
                    if not self._attempt_recovery(): break
                    last_data_time = time.time()

            # Milestone Progress Check
            if scan_duration_sec > 0:
                elapsed = current_time - start_time
                if (elapsed / scan_duration_sec) * 100 >= next_milestone_pct and next_milestone_pct <= 80:
                    self.logger.info(f"Scan progress: {next_milestone_pct}% complete.")
                    next_milestone_pct += 20

            # Status Check (Every 60 seconds)
            if (current_time - self.last_log_time) >= 60.0:
                self.logger.debug(f"Status Update: Processed {self.chunk_counter} chunks in the last 60 seconds.")
                self.chunk_counter = 0
                self.last_log_time = current_time

            # Save check
            if (current_time - last_save_time) > self.save_interval:
                self._checkpoint_data()
                last_save_time = current_time

            # Subscan check
            if subscan_enabled and (current_time - last_subscan_time) > subscan_interval_sec:
                self._rotate_subscan()
                last_subscan_time = current_time

        # Teardown
        self.radio.stop_scan()
        if self.state in [State.RUNNING, State.STOPPING]:
            self._checkpoint_data()
            
        self.state = State.IDLE
        self.scan_stopped.emit()
        self.logger.info("Scan stopped.")
        self.status_msg.emit("Scan stopped.")

    def _checkpoint_data(self):
        if not self.tracker or not self.saver or not self.current_plan: return
        
        meta = {
            'start_freq_mhz': self.current_plan.actual_start_mhz, 
            'stop_freq_mhz': self.current_plan.actual_stop_mhz,
            'bin_width_hz': self.config['bin_width'],
            'timestamp': datetime.datetime.now().isoformat()
        }
        
        self.saver.save_main(self.tracker.get_main_array(), meta)
        sub_array = None
        if self.config.get('subscan_enabled'):
            sub_array = self.tracker.get_subscan_array()
            
            if self.state == State.STOPPING:
                if self._stopped_early:
                    self.logger.info("Scan terminated early. Discarding partial subscan.")
                else:
                    # Graceful shutdown
                    scan_duration_sec = self.config.get('scan_duration_sec', 0)
                    subscan_interval_sec = self.config.get('subscan_interval_min', 30) * 60.0
                    
                    if scan_duration_sec > 0 and subscan_interval_sec > 0:
                        expected_subscans = int(scan_duration_sec // subscan_interval_sec)
                        
                        # Write the (maybe) missing subscan (solves 2-clock problem)
                        if self.subscan_count < expected_subscans:
                            self.logger.info(f"Graceful shutdown: Forcing write of final subscan ({self.subscan_count + 1}/{expected_subscans}).")
                            self.saver.save_subscan(sub_array, self.subscan_count, meta)
                        else:
                            self.logger.info(f"Graceful shutdown: Expected {expected_subscans} subscans met. Discarding remainder.")
            else:
                # Normal interval rotation during the run
                self.saver.save_subscan(sub_array, self.subscan_count, meta)
            
        self.data_updated.emit(self.tracker.get_main_array(), sub_array)

    def _rotate_subscan(self):
        self.logger.info(f"Subscan interval reached. Saving subscan {self.subscan_count}.")
        self._checkpoint_data()
        if self.tracker: self.tracker.reset_subscan()
        self.subscan_count += 1

    def _attempt_recovery(self) -> bool:
        self.radio.stop_scan()
        if self.radio.reset_radio():
            self.status_msg.emit("Software reset successful. Recalibrating.")
            time.sleep(1.0) 
            
            new_plan = self.radio.start_scan(self.config)
            if new_plan:
                # Check if hardware bounds changed after reset
                if self.current_plan and new_plan.total_bins != self.current_plan.total_bins:
                    self.logger.warning(f"Hardware layout changed after reset. DSP array changed to {new_plan.total_bins} bins.")
                    subscan_enabled = self.config.get('subscan_enabled', False)
                    self.tracker = MaxHoldTracker(new_plan.total_bins, subscan_enabled)
                
                self.current_plan = new_plan
                return True 
                
        with QMutexLocker(self._mutex):
            self.is_running = False
            self.state = State.ERROR
        self.error_occurred.emit("Hardware reset required.")
        self.hardware_reset_required.emit() 
        return False

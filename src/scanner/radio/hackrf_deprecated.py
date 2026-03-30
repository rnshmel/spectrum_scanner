import subprocess
import threading
import queue
import logging
import time
from typing import Optional

from scanner.radio.base import RadioBackend, SweepChunk, CalibrationPlan
import numpy as np

class HackRFBackend(RadioBackend):
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.data_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self.logger = logging.getLogger(__name__)
        
        self._raw_buffer = b""
        self._offset_map = {}
        self._consecutive_oob = 0

    def start_scan(self, config: dict) -> Optional[CalibrationPlan]:
        self._stop_event.clear()
        self._raw_buffer = b""
        self._offset_map = {}
        self._consecutive_oob = 0
        
        base_cmd = [
            "hackrf_sweep",
            "-f", f"{config['start_freq']}:{config['stop_freq']}",
            "-w", str(config['bin_width']),
            "-a", str(config['rf_gain']),
            "-l", str(config['if_gain']),
            "-g", str(config['bb_gain'])
        ]

        try:
            # A hackrf_sweep "one-shot"
            calib_cmd = base_cmd + ["-1"]
            self.logger.info(f"Hardware calibration dry-run: {' '.join(calib_cmd)}")
            
            # Blocking call to get exactly one interleaved sweep
            calib_process = subprocess.run(
                calib_cmd, 
                capture_output=True, 
                text=True, 
                timeout=15.0
            )
            
            if calib_process.returncode != 0:
                self.logger.error(f"Calibration sweep failed: {calib_process.stderr}")
                return None

            # Process
            parsed_chunks = []
            for line in calib_process.stdout.splitlines():
                chunk = self._parse_csv_line(line)
                if chunk:
                    parsed_chunks.append(chunk)
                    
            if not parsed_chunks:
                self.logger.error("Calibration returned no valid data.")
                return None
                
            # Sort by frequency to reconstruct the linear physical spectrum
            sorted_chunks = sorted(parsed_chunks, key=lambda x: x['mhz_low'])
            
            current_idx = 0
            for c in sorted_chunks:
                self._offset_map[c['mhz_low']] = current_idx
                # Rely strictly on measured data length.
                # The HackRF has a bug where the reported length is not correct.
                current_idx += len(c['data_db'])
                
            actual_start = sorted_chunks[0]['mhz_low']
            actual_stop = sorted_chunks[-1]['mhz_high']
            
            self.logger.info(f"Backend Calibration OK: {actual_start}M-{actual_stop}M ({current_idx} bins mapped)")
            
            plan = CalibrationPlan(
                actual_start_mhz=actual_start,
                actual_stop_mhz=actual_stop,
                total_bins=current_idx
            )
            
            # Give the OS time to release the libusb interface before reclaiming it
            time.sleep(1.0)
            
            # Main scan start
            self.logger.info(f"Starting continuous stream: {' '.join(base_cmd)}")
            self.process = subprocess.Popen(
                base_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0 
            )

            self._reader_thread = threading.Thread(target=self._stream_reader, daemon=True)
            self._reader_thread.start()
            
            return plan

        except subprocess.TimeoutExpired:
            self.logger.error("Backend calibration timed out.")
            return None
        except Exception as e:
            self.logger.error(f"Failed to start HackRF: {e}")
            return None

    def _stream_reader(self):
        if not self.process or not self.process.stdout:
            return

        while not self._stop_event.is_set():
            try:
                raw_data = self.process.stdout.read(16384)
                if not raw_data:
                    break
                
                self._raw_buffer += raw_data
                
                while b'\n' in self._raw_buffer:
                    line_bytes, self._raw_buffer = self._raw_buffer.split(b'\n', 1)
                    line_str = line_bytes.decode('utf-8', errors='ignore').strip()
                    if line_str:
                        self.data_queue.put(line_str)
            except Exception as e:
                self.logger.debug(f"Stream reader exit: {e}")
                break
        
        if self.process and self.process.stdout:
            self.process.stdout.close()

    def _get_raw_chunk(self, timeout: float) -> Optional[dict]:
        try:
            line = self.data_queue.get(timeout=timeout)
            return self._parse_csv_line(line)
        except queue.Empty:
            return None

    def read_chunk(self, timeout: float = 1.0) -> Optional[SweepChunk]:
        start_time = time.time()
        
        # Internal loop prevents CPU spinning on corrupted or ignored lines
        while (time.time() - start_time) < timeout:
            try:
                # Use a small timeout to remain responsive to stop events
                line = self.data_queue.get(timeout=0.1)
                raw = self._parse_csv_line(line)
                
                if raw:
                    start_idx = self._offset_map.get(raw['mhz_low'])
                    if start_idx is not None:
                        # Valid, mapped data
                        self._consecutive_oob = 0
                        return SweepChunk(start_index=start_idx, data_db=raw['data_db'])
                    else:
                        self._consecutive_oob += 1
                        if self._consecutive_oob < 10:
                            # Out of bounds data. Return a heartbeat so the orchestrator's
                            # watchdog doesn't accidentally trip, but the DSP layer ignores it.
                            return SweepChunk(start_index=-1, data_db=np.array([]))
                        else:
                            # After 10, we need to report a glitch/issue.
                            self.logger.error("10 consecutive OOB chunks detected.")
                            return None
                        
            except queue.Empty:
                continue
                
        # If we broke out of the while loop, it's a legitimate timeout/stall.
        return None

    def _parse_csv_line(self, line: str) -> Optional[dict]:
        if "call hackrf" in line or "Sweeping from" in line or "Stop with" in line:
            return None

        parts = [p.strip() for p in line.split(',') if p.strip()]
        if len(parts) < 7:
            return None

        try:
            if '-' not in parts[0] or ':' not in parts[1]:
                return None

            mhz_low = int(parts[2]) // 1_000_000
            mhz_high = int(parts[3]) // 1_000_000
            
            db_list = []
            for x in parts[6:]:
                try:
                    db_list.append(float(x))
                except ValueError:
                    continue
            
            if not db_list:
                return None

            return {
                'mhz_low': mhz_low, 
                'mhz_high': mhz_high, 
                'data_db': np.array(db_list, dtype=np.float32)
            }
        except (ValueError, IndexError):
            return None

    def stop_scan(self) -> None:
        self._stop_event.set()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def reset_radio(self) -> bool:
        self.logger.info("Attempting software reset of HackRF.")
        try:
            res = subprocess.run(["hackrf_info"], capture_output=True, text=True, timeout=3.0)
            return res.returncode == 0
        except Exception:
            return False

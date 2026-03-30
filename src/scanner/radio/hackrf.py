import subprocess
import threading
import queue
import logging
import time
import struct
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
        
        self._offset_map = {}
        self._consecutive_oob = 0

    def start_scan(self, config: dict) -> Optional[CalibrationPlan]:
        self._stop_event.clear()
        self._offset_map = {}
        self._consecutive_oob = 0
        
        base_cmd = [
            "hackrf_sweep",
            "-f", f"{config['start_freq']}:{config['stop_freq']}",
            "-w", str(config['bin_width']),
            "-a", str(config['rf_gain']),
            "-l", str(config['if_gain']),
            "-g", str(config['bb_gain']),
            "-B" # Binary mode
        ]

        try:
            # A hackrf_sweep "one-shot"
            calib_cmd = base_cmd + ["-1"]
            self.logger.info(f"Hardware calibration dry-run: {' '.join(calib_cmd)}")
            
            # Blocking call to get exactly one interleaved sweep
            calib_process = subprocess.run(
                calib_cmd, 
                capture_output=True, # captures raw bytes for both stdout and stderr
                timeout=15.0
            )
            
            self.logger.debug(f"Calibration process returned with code: {calib_process.returncode}")
            self.logger.debug(f"Calibration stdout length: {len(calib_process.stdout)} bytes")
            if calib_process.stderr:
                self.logger.debug(f"Calibration stderr: {calib_process.stderr.decode('utf-8', errors='ignore').strip()}")
            
            if calib_process.returncode != 0:
                err_msg = calib_process.stderr.decode('utf-8', errors='ignore')
                self.logger.error(f"Calibration sweep failed: {err_msg}")
                return None

            # Process binary output
            parsed_chunks = []
            calib_data = calib_process.stdout
            
            self.logger.debug(f"Starting to parse {len(calib_data)} bytes of calibration data.")
            idx = 0
            
            # HackRF Sweep Binary Format (-B mode)
            # The binary stream outputs contiguous memory blocks.
            # Header (20 bytes):
            # [ 4 bytes] uint32_t = record_length (Size of the data that follows)
            # [ 8 bytes] uint64_t = hz_low (Lower frequency bound in Hz)
            # [ 8 bytes] uint64_t = hz_high (Upper frequency bound in Hz)
            # Payload (record_length - 16 bytes):
            # Contiguous array of float32 dB power values for each FFT bin.
            while idx + 20 <= len(calib_data):
                record_length, hz_low, hz_high = struct.unpack('<IQQ', calib_data[idx:idx+20])
                idx += 20
                
                # The C source defines record_length as 16 bytes (the two uint64s) + payload bytes.
                # It does NOT include the 4 bytes of the record_length integer itself.
                payload_len = record_length - 16
                
                if payload_len < 0 or idx + payload_len > len(calib_data):
                    self.logger.warning(f"Incomplete payload at idx {idx}. Expected {payload_len} bytes, got {len(calib_data) - idx}.")
                    break
                
                payload = calib_data[idx:idx+payload_len]
                data_db = np.frombuffer(payload, dtype=np.float32)
                
                if len(data_db) > 0:
                    parsed_chunks.append({
                        'mhz_low': hz_low // 1_000_000,
                        'mhz_high': hz_high // 1_000_000,
                        'data_db': data_db
                    })
                    
                idx += payload_len
                
            if not parsed_chunks:
                self.logger.error("Calibration returned no valid data.")
                return None
                
            # Sort by frequency to reconstruct the linear physical spectrum
            sorted_chunks = sorted(parsed_chunks, key=lambda x: x['mhz_low'])
            
            current_idx = 0
            for c in sorted_chunks:
                self._offset_map[c['mhz_low']] = current_idx
                # We still rely strictly on measured data length here, 
                # shielding the DSP allocator from HackRF math bugs.
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
                stderr=subprocess.DEVNULL, # Prevents text errors from corrupting the binary stdout
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

    def _read_exact(self, stream, size: int) -> Optional[bytes]:
        # Helper to ensure we pull exactly 'size' bytes from the unbuffered pipe
        data = bytearray()
        while len(data) < size:
            if self._stop_event.is_set():
                return None
            chunk = stream.read(size - len(data))
            if not chunk:
                return None
            data.extend(chunk)
        return bytes(data)

    def _stream_reader(self):
        if not self.process or not self.process.stdout:
            return

        while not self._stop_event.is_set():
            try:
                # Read the 20-byte fixed header: <IQQ
                header_bytes = self._read_exact(self.process.stdout, 20)
                if not header_bytes:
                    break
                
                record_length, hz_low, hz_high = struct.unpack('<IQQ', header_bytes)
                
                # The C source defines record_length as 16 bytes (the two uint64s) + payload bytes.
                payload_length = record_length - 16
                if payload_length <= 0:
                    continue
                    
                payload = self._read_exact(self.process.stdout, payload_length)
                if not payload:
                    break
                
                data_db = np.frombuffer(payload, dtype=np.float32)
                if len(data_db) > 0:
                    self.data_queue.put({
                        'mhz_low': hz_low // 1_000_000,
                        'mhz_high': hz_high // 1_000_000,
                        'data_db': data_db
                    })
                    
            except Exception as e:
                self.logger.debug(f"Stream reader exit: {e}")
                break
        
        if self.process and self.process.stdout:
            self.process.stdout.close()

    def read_chunk(self, timeout: float = 1.0) -> Optional[SweepChunk]:
        start_time = time.time()
        
        # Internal loop prevents CPU spinning on corrupted or ignored lines
        while (time.time() - start_time) < timeout:
            try:
                # Use a small timeout to remain responsive to stop events
                raw = self.data_queue.get(timeout=0.1)
                
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

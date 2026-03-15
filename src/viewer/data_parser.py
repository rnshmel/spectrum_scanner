import json
import logging
import numpy as np
from dataclasses import dataclass
from typing import Optional

@dataclass
class ScanData:
    start_freq_mhz: int
    stop_freq_mhz: int
    bin_width_hz: int
    timestamp: str
    data_db: np.ndarray

# Reads .dat files produced by the SDR Scanner.
# Extracts the JSON metadata header and decodes the binary float32 payload.
class DatFileParser:
    @staticmethod
    def parse(filepath: str) -> Optional[ScanData]:
        logger = logging.getLogger(__name__)
        
        try:
            with open(filepath, 'rb') as f:
                # Use readline()
                # Note: this means metadata must be seperated from data via a newline
                first_line = f.readline().decode('utf-8').strip()
                
                if not first_line.startswith('# METADATA: '):
                    logger.error(f"Invalid file format: Missing metadata header in {filepath}")
                    return None
                
                json_str = first_line.replace('# METADATA: ', '')
                meta = json.loads(json_str)
                
                # Read the rest as raw bytes
                raw_bytes = f.read()
                data_array = np.frombuffer(raw_bytes, dtype=np.float32)
                
                return ScanData(
                    start_freq_mhz=meta.get('start_freq_mhz', 0),
                    stop_freq_mhz=meta.get('stop_freq_mhz', 0),
                    bin_width_hz=meta.get('bin_width_hz', 0),
                    timestamp=meta.get('timestamp', ''),
                    data_db=data_array
                )
                
        except Exception as e:
            logger.error(f"Failed to parse {filepath}: {e}")
            return None

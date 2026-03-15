import numpy as np
from typing import Optional

from scanner.radio.base import SweepChunk

class MaxHoldTracker:

    def __init__(self, total_bins: int, subscan_enabled: bool = False):
        self.subscan_enabled = subscan_enabled
        self.total_bins = total_bins
        
        # Initialize with unrealistic low noise floor.
        self.main_array = np.full(self.total_bins, -1000.0, dtype=np.float32)
        
        if self.subscan_enabled:
            self.subscan_array = np.full(self.total_bins, -1000.0, dtype=np.float32)
        else:
            self.subscan_array = None

    def update(self, chunk: SweepChunk):
        start = chunk.start_index
        end = start + len(chunk.data_db)
        
        # Safety bounds check
        if end > self.total_bins:
            return
        
        self.main_array[start:end] = np.maximum(self.main_array[start:end], chunk.data_db)
        
        if self.subscan_array is not None:
            self.subscan_array[start:end] = np.maximum(self.subscan_array[start:end], chunk.data_db)

    def reset_subscan(self):
        if self.subscan_array is not None:
            self.subscan_array.fill(-1000.0)

    def get_main_array(self) -> np.ndarray:
        return self.main_array

    def get_subscan_array(self) -> Optional[np.ndarray]:
        return self.subscan_array

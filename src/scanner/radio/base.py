import abc
from dataclasses import dataclass
from typing import Optional
import numpy as np

@dataclass
class CalibrationPlan:
    actual_start_mhz: int
    actual_stop_mhz: int
    total_bins: int

# Standardized data object that ALL radio backends must yield.
# Contains only the exact memory offset and the raw data.
@dataclass
class SweepChunk:
    start_index: int # The exact offset where this data belongs in the main array
    data_db: np.ndarray # 1D numpy array of float32 dB values


class RadioBackend(abc.ABC):

    # Initializes the radio, performs any required calibration/dry-runs.
    # Returns a concrete plan for the DSP memory allocator.
    # Very SDR dependent.
    @abc.abstractmethod
    def start_scan(self, config: dict) -> Optional[CalibrationPlan]:
        pass

    @abc.abstractmethod
    def stop_scan(self) -> None:
        pass

    # Get the next chunk of data, fully mapped with a start_index.
    @abc.abstractmethod
    def read_chunk(self, timeout: float = 1.0) -> Optional[SweepChunk]:
        pass

    # Used to recover from a radio issue mid-scan.
    @abc.abstractmethod
    def reset_radio(self) -> bool:
        pass

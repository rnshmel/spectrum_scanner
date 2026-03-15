import os
import json
import logging
import numpy as np
from typing import Dict, Any


# Writes data to a temporary file first, then uses an OS-level atomic
# to safely overwrite the target file. This prevents losing the whole
# scan if something crashes.
class AtomicSaver:

    def __init__(self, save_dir: str, base_filename: str):
        self.logger = logging.getLogger(__name__)
        self.save_dir = save_dir
        
        # Strip any existing extension
        if base_filename.endswith('.dat'):
            base_filename = base_filename[:-4]
            
        self.base_filename = base_filename
        
        # Ensure the output directory exists
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
            self.logger.info(f"Created save directory: {self.save_dir}")

    def save_main(self, array: np.ndarray, metadata: Dict[str, Any]):
        file_path = os.path.join(self.save_dir, f"{self.base_filename}.dat")
        self._atomic_write(file_path, array, metadata)

    def save_subscan(self, array: np.ndarray, subscan_count: int, metadata: Dict[str, Any]):
        file_path = os.path.join(self.save_dir, f"{self.base_filename}_{subscan_count}.dat")
        self._atomic_write(file_path, array, metadata)

    def _atomic_write(self, target_filepath: str, array: np.ndarray, metadata: Dict[str, Any]):
        # Create a temporary file path
        tmp_filepath = f"{target_filepath}.tmp"
        
        try:
            # Write metadata as a JSON string on the first line, encoded to bytes
            with open(tmp_filepath, 'wb') as f:
                header = f"# METADATA: {json.dumps(metadata)}\n"
                f.write(header.encode('utf-8'))
                
                f.write(array.astype(np.float32).tobytes())
                
            # Replaces target_filepath with tmp_filepath
            os.replace(tmp_filepath, target_filepath)
            
            self.logger.debug(f"Saved: {target_filepath}")
            
        except Exception as e:
            self.logger.error(f"Failed to save {target_filepath}: {e}")

            # Try to clean up the orphaned .tmp file if the write failed midway
            if os.path.exists(tmp_filepath):
                try:
                    os.remove(tmp_filepath)
                except OSError:
                    pass

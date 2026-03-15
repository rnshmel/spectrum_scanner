import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy.signal import find_peaks
from sklearn.cluster import DBSCAN
from scipy.ndimage import median_filter, uniform_filter1d

# Reusable DSP filtering operations for spectrum arrays.
class SpectrumFilters:
    
    @staticmethod
    def apply_moving_average(data: np.ndarray, window_len: int) -> np.ndarray:
        if window_len < 3: return data
        return uniform_filter1d(data, size=window_len, mode='nearest')

    @staticmethod
    def apply_gaussian(data: np.ndarray, window_len: int) -> np.ndarray:
        if window_len < 3: return data
        pad_size = window_len // 2
        padded = np.pad(data, (pad_size, pad_size), mode='edge')
        sigma = (window_len - 1) / 6.0
        x = np.arange(-pad_size, pad_size + 1)
        kernel = np.exp(-0.5 * (x / sigma) ** 2)
        kernel /= kernel.sum() 
        return np.convolve(padded, kernel, mode='valid')

    @staticmethod
    def apply_sliding_median(data: np.ndarray, window_len: int) -> np.ndarray:
        if window_len < 3: return data
        return median_filter(data, size=window_len, mode='reflect')

    @staticmethod
    def find_spectrum_peaks(data: np.ndarray, height_thresh=None, prominence: float = 3.0, distance: int = 10, width: int = 3):
        peaks, properties = find_peaks(data, height=height_thresh, prominence=prominence, distance=distance, width=width)
        return peaks, properties

    # Clusters detected peaks into logical signals using DBSCAN.
    # Note: converts widths to MHz to establish a 1:1 physical spatial weighting with freq.
    @staticmethod
    def cluster_peaks(freqs: list, widths: list, powers: list, prominences: list, sources: list = None, eps: float = 0.5, min_samples: int = 1):

        if len(freqs) == 0:
            return []

        # This normalizes the euclidean distance to MHz
        # eps = 'freq' radius in MHz (default = 0.1 = 100 kHz)
        widths_mhz = np.array(widths) / 1000.0

        # X = Frequency in MHz, Y = Width in MHz
        X_scaled = np.column_stack((freqs, widths_mhz))

        db = DBSCAN(eps=eps, min_samples=min_samples).fit(X_scaled)
        labels = db.labels_

        # Aggregate the clusters
        clusters = []
        unique_labels = set(labels)
        
        for label in unique_labels:
            mask = (labels == label)
            cluster_freqs = np.array(freqs)[mask]
            cluster_widths = np.array(widths)[mask]
            cluster_powers = np.array(powers)[mask]
            
            is_noise = (label == -1)
            
            # Cross-file math
            unique_src_count = 1
            if sources is not None:
                cluster_sources = np.array(sources)[mask]
                unique_src_count = len(set(cluster_sources))
            
            clusters.append({
                'cluster_id': "Noise" if is_noise else f"Sig-{label+1}",
                'is_noise': is_noise,
                'avg_freq': np.mean(cluster_freqs),
                'avg_width': np.mean(cluster_widths),
                'peak_power': np.max(cluster_powers),
                'hit_count': len(cluster_freqs),
                'unique_sources': unique_src_count,
                'raw_freqs': cluster_freqs,
                'raw_widths': cluster_widths
            })

        # Sort clusters by freq
        clusters.sort(key=lambda x: x['avg_freq'])
        return clusters

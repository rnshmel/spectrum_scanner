# SDR Survey and Analysis Suite

*Version 1.0.0*

A graphical Software Defined Radio (SDR) survey tool designed for long-duration RF monitoring and post-scan analysis.

Built with **Python 3**, **PyQt5**, **NumPy**, and **SciPy/Scikit-learn**, this suite separates hardware acquisition from post-processing to improve stability during long sweeps.

## Architecture Overview

The suite is divided into two applications:

1. **Spectrum Scanner (`spectrum_scanner.py`)**: An acquisition-focused UI that wraps SDR libraries within a QThread orchestrator. It parses data streams directly into NumPy arrays and is robust enough for long-running scans.
2. **Scan Viewer (`scan_viewer.py`)**: A PyQtGraph-based analysis environment for post-processing large `.dat` files with tunable DSP filters, peak extraction, density-based emitter clustering (WIP), and spectrograms.

TODO:
* Add support for RTL-SDR
* Add support for B-series USRPs
* Better clustering analysis.

## Key Features

### Acquisition (Scanner)
* **Atomic Checkpointing**: Utilizes OS-level file replacement (`.tmp` to `.dat`) to prevent data corruption during unexpected errors in scanning.
* **Hardware Watchdog**: Monitors the SDR data stream for stalls, automatically attempting software resets of the SDR subprocess to maintain scan continuity.
* **Subscans**: Segments sweeps into discrete time intervals while simultaneously maintaining a cumulative main max-hold file.

### Analysis (Viewer)
* **DSP Pipeline**: Apply Moving Average or Gaussian smoothing, and calculate sliding-median noise floors across the FFT bin array.
* **Automated Peak Extraction**: Leverages SciPy's `find_peaks` to isolate signals based on Prominence, Separation (Distance), and Width thresholds.
* **Emitter Classification (DBSCAN)**: Applies Density-Based Spatial Clustering (from Scikit-learn) to map Center Frequency against Bandwidth across multiple scans, categorizing peaks by cross-file persistence. *Still a WIP.*
* **Headless Bulk Ingest**: Batch process raw scan files using active DSP parameters, extracting structured emitter data directly to CSV without GUI rendering overhead.
* **Temporal Spectrogram**: Render sequential subscan directories into a waterfall plot for long time-domain observation.

## Installation

**1. Install System Dependencies (SDR Drivers)**
Ensure you have the HackRF host tools installed on your OS:
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install hackrf
```

**2. Setup Python Environment**
```bash
git clone https://github.com/rnshmel/spectrum_scanner/
cd spectrum_scanner

# The run script handles virtual environments and dependencies automatically
chmod +x run.sh
```

## Usage

The repository uses a unified launch script that manages the `PYTHONPATH` and virtual environments.

**Launch the Acquisition Scanner:**
```bash
./run.sh spectrum_scanner.py
```

**Launch the Analysis Viewer:**
```bash
./run.sh scan_viewer.py
```

## 🛠️ Extensibility
The scanner backend is built on an abstract `RadioBackend` class to allow support for multiple SDRs.

---
### License

This project is licensed under the MIT License. See the LICENSE file for details.

**Author:** **Richard N Shmel** | Electrical Engineer
* [RNS Tech Solutions LLC](https://www.rnstechsolutions.com/)
* [LinkedIn](https://www.linkedin.com/in/richard-shmel)
* [GitHub](https://github.com/rnshmel)

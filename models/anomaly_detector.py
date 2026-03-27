"""Shim for models.anomaly_detector

Re-exports symbols from the top-level `anomaly_detector.py` file.
"""
from anomaly_detector import (
    KeywordAnomalyDetector,
    get_anomaly_detector,
)

__all__ = ["KeywordAnomalyDetector", "get_anomaly_detector"]

"""Shim for data_pipeline.spark_log_processor

Re-exports symbols from the top-level `spark_log_processor.py` file so imports
using `data_pipeline.spark_log_processor` work without moving the original file.
"""
from spark_log_processor import (
    PandasLogProcessor,
)

__all__ = ["PandasLogProcessor"]

"""
data_pipeline/spark_log_processor.py

PySpark pipeline that:
1. Ingests raw log files (batch or streaming)
2. Parses structured fields from raw log lines
3. Computes anomaly signals — error rate, spike detection, pattern frequency
4. Returns a Pandas DataFrame of flagged log windows to the agent
"""

import re
import pandas as pd
from datetime import datetime
from typing import Optional
from loguru import logger

# ── Try importing PySpark; fall back to Pandas-only mode if unavailable ──────
try:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        StructType, StructField, StringType, TimestampType, IntegerType
    )
    SPARK_AVAILABLE = True
except ImportError:
    SPARK_AVAILABLE = False
    logger.warning("PySpark not available — running in Pandas-only mode")

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config.settings import settings


# ─── Log line regex ───────────────────────────────────────────────────────────
LOG_PATTERN = re.compile(
    r"\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]"
    r"\s\[(?P<level>\w+)\]"
    r"\s\[(?P<service>[\w\-]+)\]"
    r"\s\[(?P<thread>[\w\-]+)\]"
    r"\s(?P<message>.+)"
)

ERROR_LEVELS = {"ERROR", "FATAL", "CRITICAL"}


def parse_log_line(line: str) -> Optional[dict]:
    """Parse a single log line into a structured dict."""
    m = LOG_PATTERN.match(line.strip())
    if not m:
        return None
    return {
        "timestamp": datetime.strptime(m.group("timestamp"), "%Y-%m-%d %H:%M:%S"),
        "level":     m.group("level"),
        "service":   m.group("service"),
        "thread":    m.group("thread"),
        "message":   m.group("message"),
        "is_error":  m.group("level") in ERROR_LEVELS,
    }


# ─── Pandas pipeline (always available) ───────────────────────────────────────

class PandasLogProcessor:
    """
    Lightweight log processor using Pandas.
    Used when PySpark is unavailable or for small log files.
    """

    def load_log_file(self, filepath: str) -> pd.DataFrame:
        rows = []
        with open(filepath, "r") as f:
            for line in f:
                parsed = parse_log_line(line)
                if parsed:
                    rows.append(parsed)
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        logger.info(f"Loaded {len(df)} log lines from {filepath}")
        return df

    def compute_error_rate(self, df: pd.DataFrame, window_minutes: int = 5) -> pd.DataFrame:
        """
        Compute rolling error rate per time window.
        Returns windows where error rate exceeds threshold.
        """
        if df.empty:
            return df
        df = df.set_index("timestamp")
        rule = f"{window_minutes}min"
        windowed = df.resample(rule).agg(
            total=("is_error", "count"),
            errors=("is_error", "sum"),
        ).reset_index()
        windowed["error_rate"] = windowed["errors"] / windowed["total"].replace(0, 1)
        return windowed

    def detect_anomaly_windows(
        self, df: pd.DataFrame, error_rate_threshold: float = 0.30
    ) -> pd.DataFrame:
        """
        Find time windows with abnormally high error rates.
        Returns flagged windows with context logs.
        """
        windowed = self.compute_error_rate(df)
        flagged  = windowed[windowed["error_rate"] >= error_rate_threshold].copy()
        flagged["anomaly"] = True
        logger.info(f"Detected {len(flagged)} anomaly windows (threshold={error_rate_threshold})")
        return flagged

    def extract_error_logs(self, df: pd.DataFrame, last_n: int = 100) -> pd.DataFrame:
        """Return the most recent error/fatal log lines."""
        errors = df[df["is_error"]].tail(last_n)
        return errors

    def service_error_summary(self, df: pd.DataFrame) -> pd.DataFrame:
        """Group errors by service to identify worst offender."""
        return (
            df[df["is_error"]]
            .groupby("service")
            .agg(error_count=("is_error", "sum"))
            .sort_values("error_count", ascending=False)
            .reset_index()
        )

    def get_recent_logs_as_text(self, df: pd.DataFrame, n: int = 50) -> str:
        """Return last N log lines as plain text for LLM context."""
        recent = df.tail(n)
        lines  = recent.apply(
            lambda r: f"[{r['timestamp']}] [{r['level']}] [{r['service']}] {r['message']}",
            axis=1,
        )
        return "\n".join(lines.tolist())


# ─── PySpark pipeline (production scale) ──────────────────────────────────────

class SparkLogProcessor:
    """
    PySpark-based log processor for large-scale log files.
    Handles GB-scale log ingestion with distributed processing.
    """

    def __init__(self):
        self.spark = (
            SparkSession.builder
            .appName(settings.SPARK_APP_NAME)
            .master(settings.SPARK_MASTER)
            .config("spark.sql.shuffle.partitions", "8")
            .getOrCreate()
        )
        self.spark.sparkContext.setLogLevel("ERROR")
        logger.info("SparkSession initialized")

    def load_log_file(self, filepath: str):
        """Load and parse log file into Spark DataFrame."""
        raw = self.spark.read.text(filepath)

        @F.udf(returnType=StructType([
            StructField("timestamp", StringType()),
            StructField("level",     StringType()),
            StructField("service",   StringType()),
            StructField("thread",    StringType()),
            StructField("message",   StringType()),
            StructField("is_error",  StringType()),
        ]))
        def parse_udf(line):
            m = LOG_PATTERN.match(line.strip()) if line else None
            if not m:
                return None
            return (
                m.group("timestamp"),
                m.group("level"),
                m.group("service"),
                m.group("thread"),
                m.group("message"),
                str(m.group("level") in ERROR_LEVELS),
            )

        parsed = (
            raw.select(parse_udf("value").alias("parsed"))
            .filter(F.col("parsed").isNotNull())
            .select(
                F.to_timestamp("parsed.timestamp", "yyyy-MM-dd HH:mm:ss").alias("timestamp"),
                F.col("parsed.level").alias("level"),
                F.col("parsed.service").alias("service"),
                F.col("parsed.thread").alias("thread"),
                F.col("parsed.message").alias("message"),
                (F.col("parsed.is_error") == "True").alias("is_error"),
            )
        )
        logger.info(f"Loaded log file via Spark: {filepath}")
        return parsed

    def detect_anomaly_windows(self, sdf, window_minutes: int = 5, threshold: float = 0.30):
        """Compute error rate per window using Spark window functions."""
        windowed = (
            sdf.groupBy(
                F.window("timestamp", f"{window_minutes} minutes"),
                "service",
            )
            .agg(
                F.count("*").alias("total"),
                F.sum(F.col("is_error").cast("int")).alias("errors"),
            )
            .withColumn("error_rate", F.col("errors") / F.col("total"))
            .filter(F.col("error_rate") >= threshold)
            .orderBy("window.start", ascending=False)
        )
        return windowed

    def to_pandas(self, sdf) -> pd.DataFrame:
        """Convert Spark DataFrame to Pandas for agent consumption."""
        return sdf.toPandas()

    def stop(self):
        self.spark.stop()


# ─── Unified interface ─────────────────────────────────────────────────────────

def get_log_processor():
    """Return SparkLogProcessor if available, else PandasLogProcessor."""
    if SPARK_AVAILABLE:
        logger.info("Using PySpark log processor")
        return SparkLogProcessor()
    logger.info("Using Pandas log processor")
    return PandasLogProcessor()


if __name__ == "__main__":
    # Quick test with sample data
    import sys
    sys.path.insert(0, "..")
    from datasets.generate_sample_logs import generate_incident_log

    generate_incident_log()

    proc = PandasLogProcessor()
    df   = proc.load_log_file("datasets/sample_logs/incident.log")

    print("\n📊 Error Rate by Window:")
    print(proc.compute_error_rate(df).tail(10).to_string(index=False))

    print("\n🚨 Anomaly Windows:")
    print(proc.detect_anomaly_windows(df).to_string(index=False))

    print("\n🔴 Service Error Summary:")
    print(proc.service_error_summary(df).to_string(index=False))

    print("\n📝 Recent Error Logs (last 5):")
    print(proc.extract_error_logs(df).tail(5)[["timestamp", "level", "service", "message"]].to_string(index=False))

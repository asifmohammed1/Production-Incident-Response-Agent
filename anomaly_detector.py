"""
models/anomaly_detector.py

HuggingFace-based log anomaly detection.
Uses sentence-transformers to embed log lines and detect
semantic anomalies by measuring cosine distance from
a "normal" baseline corpus.

Also includes a lightweight keyword-based fallback
that requires zero GPU/model downloads.
"""

import os
import json
import numpy as np
import pandas as pd
from typing import List, Tuple
from loguru import logger

# ── Try loading sentence-transformers ─────────────────────────────────────────
try:
    from sentence_transformers import SentenceTransformer
    import torch
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False
    logger.warning("sentence-transformers not available — using keyword-based detector")

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config.settings import settings


# ─── Keyword-based detector (zero dependencies, always works) ─────────────────

CRITICAL_KEYWORDS = [
    "out of memory", "heap", "connection refused", "timeout",
    "circuit breaker", "fatal", "crash", "unhandled exception",
    "disk i/o error", "thread pool exhausted", "null pointer",
    "ssl handshake failed", "rejected", "shutting down",
    "status 500", "status 503", "status 502",
]

SEVERITY_MAP = {
    "FATAL":    1.0,
    "CRITICAL": 0.95,
    "ERROR":    0.75,
    "WARN":     0.40,
    "DEBUG":    0.05,
    "INFO":     0.02,
}


class KeywordAnomalyDetector:
    """
    Fast, zero-dependency anomaly scorer using
    keyword matching + log level weighting.
    """

    def score_line(self, message: str, level: str) -> float:
        """Return anomaly score 0.0–1.0 for a single log line."""
        base  = SEVERITY_MAP.get(level.upper(), 0.1)
        lower = message.lower()
        keyword_hits = sum(1 for kw in CRITICAL_KEYWORDS if kw in lower)
        bonus = min(keyword_hits * 0.15, 0.5)
        return min(base + bonus, 1.0)

    def score_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Score all log lines in a DataFrame."""
        df = df.copy()
        df["anomaly_score"] = df.apply(
            lambda r: self.score_line(r.get("message", ""), r.get("level", "INFO")),
            axis=1,
        )
        df["is_anomaly"] = df["anomaly_score"] >= settings.HF_ANOMALY_THRESHOLD
        return df

    def get_top_anomalies(self, df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
        scored = self.score_dataframe(df)
        return (
            scored[scored["is_anomaly"]]
            .sort_values("anomaly_score", ascending=False)
            .head(top_n)
        )


# ─── HuggingFace Semantic Anomaly Detector ────────────────────────────────────

class SemanticAnomalyDetector:
    """
    Uses sentence-transformers to embed log messages.
    Detects anomalies by measuring cosine distance from
    a baseline of 'normal' log embeddings.

    Training: feed it normal logs → it learns what normal looks like.
    Inference: new logs that deviate semantically are flagged.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        logger.info(f"Loading embedding model: {model_name}")
        self.model          = SentenceTransformer(model_name)
        self.normal_centroid: np.ndarray = None
        self.normal_std: float           = None
        self.threshold: float            = settings.HF_ANOMALY_THRESHOLD
        logger.info("Semantic anomaly detector ready")

    def fit(self, normal_messages: List[str]) -> None:
        """
        Fit the detector on a corpus of normal log messages.
        Computes the centroid embedding of the normal distribution.
        """
        logger.info(f"Fitting on {len(normal_messages)} normal log messages...")
        embeddings = self.model.encode(
            normal_messages,
            batch_size=64,
            show_progress_bar=True,
            convert_to_numpy=True,
        )
        self.normal_centroid = embeddings.mean(axis=0)
        # Compute std of cosine distances from centroid
        dists = self._cosine_distances(embeddings, self.normal_centroid)
        self.normal_std = dists.std()
        logger.info(f"Fit complete. Normal std: {self.normal_std:.4f}")

    def _cosine_distances(self, embeddings: np.ndarray, centroid: np.ndarray) -> np.ndarray:
        """Compute cosine distance from each embedding to centroid."""
        norm_emb = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-9)
        norm_cen = centroid / (np.linalg.norm(centroid) + 1e-9)
        similarities = norm_emb @ norm_cen
        return 1 - similarities  # distance = 1 - similarity

    def score_messages(self, messages: List[str]) -> np.ndarray:
        """
        Return anomaly scores (0–1) for a list of log messages.
        Higher = more anomalous.
        """
        if self.normal_centroid is None:
            raise RuntimeError("Detector not fitted. Call .fit() with normal logs first.")

        embeddings = self.model.encode(
            messages,
            batch_size=64,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        distances = self._cosine_distances(embeddings, self.normal_centroid)
        # Normalize: score = distance / (centroid_std * 3) capped at 1.0
        normalizer = max(self.normal_std * 3, 0.01)
        scores     = np.clip(distances / normalizer, 0.0, 1.0)
        return scores

    def score_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Score all log messages in a DataFrame."""
        df = df.copy()
        messages = df["message"].fillna("").tolist()
        scores   = self.score_messages(messages)
        df["anomaly_score"] = scores
        df["is_anomaly"]    = scores >= self.threshold
        return df

    def get_top_anomalies(self, df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
        scored = self.score_dataframe(df)
        return (
            scored[scored["is_anomaly"]]
            .sort_values("anomaly_score", ascending=False)
            .head(top_n)
        )

    def save(self, path: str) -> None:
        """Save centroid + std to disk."""
        os.makedirs(path, exist_ok=True)
        np.save(os.path.join(path, "centroid.npy"), self.normal_centroid)
        with open(os.path.join(path, "meta.json"), "w") as f:
            json.dump({"std": self.normal_std, "threshold": self.threshold}, f)
        logger.info(f"Detector saved to {path}")

    def load(self, path: str) -> None:
        """Load centroid + std from disk."""
        self.normal_centroid = np.load(os.path.join(path, "centroid.npy"))
        with open(os.path.join(path, "meta.json")) as f:
            meta = json.load(f)
        self.normal_std = meta["std"]
        self.threshold  = meta.get("threshold", self.threshold)
        logger.info(f"Detector loaded from {path}")


# ─── Unified factory ───────────────────────────────────────────────────────────

def get_anomaly_detector(use_semantic: bool = None):
    """
    Returns SemanticAnomalyDetector if HuggingFace is available,
    else KeywordAnomalyDetector.
    """
    if use_semantic is None:
        use_semantic = HF_AVAILABLE
    if use_semantic and HF_AVAILABLE:
        return SemanticAnomalyDetector()
    return KeywordAnomalyDetector()


if __name__ == "__main__":
    # Quick smoke test
    import sys
    sys.path.insert(0, "..")
    from datasets.generate_sample_logs import generate_normal_log, generate_incident_log
    from data_pipeline.spark_log_processor import PandasLogProcessor

    generate_normal_log()
    generate_incident_log()

    proc    = PandasLogProcessor()
    normal  = proc.load_log_file("datasets/sample_logs/normal.log")
    incident= proc.load_log_file("datasets/sample_logs/incident.log")

    detector = KeywordAnomalyDetector()

    print("\n🔍 Scoring incident logs...")
    scored = detector.score_dataframe(incident)
    top    = detector.get_top_anomalies(incident, top_n=10)

    print(f"Total anomalies detected: {scored['is_anomaly'].sum()}")
    print("\nTop anomalous log lines:")
    print(top[["timestamp", "level", "service", "anomaly_score", "message"]].to_string(index=False))

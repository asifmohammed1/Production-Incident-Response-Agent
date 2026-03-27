"""Shim for models.ollama_client

Re-exports the `ollama_client` instance from the top-level `ollama_client.py`.
"""
from ollama_client import ollama_client

__all__ = ["ollama_client"]

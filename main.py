"""
api/main.py

FastAPI REST API for the Incident Response Agent.

Endpoints:
  POST /api/analyze          → Trigger analysis on a log file
  GET  /api/incidents        → List past incidents
  GET  /api/incidents/{id}   → Get a specific incident
  GET  /api/tools            → List available MCP tools
  POST /api/tools/{name}     → Run a specific MCP tool
  GET  /api/health           → Health check
  GET  /api/stream           → SSE stream of live log events
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from typing import Optional, List
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from loguru import logger

from agents.incident_agent import run_incident_pipeline, IncidentState
from mcp_tools.mcp_server import mcp_server
from data_pipeline.spark_log_processor import PandasLogProcessor
from models.anomaly_detector import get_anomaly_detector
from config.settings import settings

app = FastAPI(
    title="Incident Response Agent API",
    description="Auto-Pilot for Production Outages",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store (replace with MongoDB in production)
incident_store: List[dict] = []


# ─── Request / Response Models ────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    log_path: Optional[str] = None    # defaults to watch dir
    log_content: Optional[str] = None # inline log text

class ToolRunRequest(BaseModel):
    parameters: dict = {}

class IncidentResponse(BaseModel):
    incident_id: str
    triggered_at: str
    anomaly_detected: bool
    severity: str
    affected_services: List[str]
    error_rate: float
    root_cause: str
    fix_suggestion: str
    ticket_key: str
    slack_status: str
    incident_report: str
    agent_log: List[str]
    completed_at: str


# ─── Background task ──────────────────────────────────────────────────────────

def _run_pipeline_bg(log_path: str, incident_id: str):
    """Run the incident pipeline in background and store result."""
    try:
        result = run_incident_pipeline(log_path)
        record = {
            "incident_id": incident_id,
            **result,
        }
        incident_store.append(record)
        logger.info(f"Pipeline complete for {incident_id}")
    except Exception as e:
        logger.error(f"Pipeline failed for {incident_id}: {e}")
        incident_store.append({
            "incident_id": incident_id,
            "error": str(e),
            "triggered_at": datetime.now().isoformat(),
        })


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "mcp_tools": len(mcp_server.tools),
        "ollama_model": settings.OLLAMA_MODEL,
    }


@app.get("/api/tools")
def list_tools():
    """List all available MCP tools."""
    return {"tools": mcp_server.list_tools()}


@app.post("/api/tools/{tool_name}")
def run_tool(tool_name: str, body: ToolRunRequest):
    """Run a specific MCP tool with given parameters."""
    result = mcp_server.run(tool_name, **body.parameters)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/analyze")
async def analyze_logs(body: AnalyzeRequest, background_tasks: BackgroundTasks):
    """
    Trigger incident analysis.
    - If log_content is provided, writes to temp file and analyzes.
    - If log_path is provided, analyzes that file.
    - Otherwise, analyzes the default watch directory log.
    """
    incident_id = f"INC-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # Resolve log path
    if body.log_content:
        # Write inline content to temp file
        tmp_path = os.path.join(settings.LOG_WATCH_DIR, f"tmp_{incident_id}.log")
        os.makedirs(settings.LOG_WATCH_DIR, exist_ok=True)
        with open(tmp_path, "w") as f:
            f.write(body.log_content)
        log_path = tmp_path
    elif body.log_path:
        log_path = body.log_path
    else:
        log_path = os.path.join(settings.LOG_WATCH_DIR, "incident.log")

    if not os.path.exists(log_path):
        raise HTTPException(
            status_code=404,
            detail=f"Log file not found: {log_path}. "
                   "Run datasets/generate_sample_logs.py to create test data."
        )

    # Run pipeline in background
    background_tasks.add_task(_run_pipeline_bg, log_path, incident_id)

    return {
        "incident_id": incident_id,
        "status": "processing",
        "message": f"Analysis started. Poll GET /api/incidents/{incident_id} for results.",
        "log_path": log_path,
    }


@app.post("/api/analyze/sync")
def analyze_logs_sync(body: AnalyzeRequest):
    """
    Synchronous version of analyze — waits for result.
    Use for testing; prefer async in production.
    """
    incident_id = f"INC-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    if body.log_content:
        tmp_path = os.path.join(settings.LOG_WATCH_DIR, f"tmp_{incident_id}.log")
        os.makedirs(settings.LOG_WATCH_DIR, exist_ok=True)
        with open(tmp_path, "w") as f:
            f.write(body.log_content)
        log_path = tmp_path
    elif body.log_path:
        log_path = body.log_path
    else:
        log_path = os.path.join(settings.LOG_WATCH_DIR, "incident.log")

    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail=f"Log file not found: {log_path}")

    result = run_incident_pipeline(log_path)
    record = {"incident_id": incident_id, **result}
    incident_store.append(record)
    return record


@app.get("/api/incidents")
def list_incidents(limit: int = 20):
    """List all analyzed incidents, most recent first."""
    return {
        "incidents": list(reversed(incident_store))[:limit],
        "total": len(incident_store),
    }


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    """Get a specific incident by ID."""
    for inc in incident_store:
        if inc.get("incident_id") == incident_id:
            return inc
    raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")


@app.get("/api/stats")
def get_stats():
    """Summary statistics of all analyzed incidents."""
    if not incident_store:
        return {"total": 0, "message": "No incidents analyzed yet"}

    anomalies = [i for i in incident_store if i.get("anomaly_detected")]
    severities = {}
    for i in anomalies:
        sev = i.get("severity", "Unknown").split()[0]
        severities[sev] = severities.get(sev, 0) + 1

    services = {}
    for i in anomalies:
        for s in i.get("affected_services", []):
            services[s] = services.get(s, 0) + 1

    return {
        "total_analyzed":    len(incident_store),
        "anomalies_found":   len(anomalies),
        "false_negatives":   len(incident_store) - len(anomalies),
        "severity_breakdown":severities,
        "top_services":      dict(sorted(services.items(), key=lambda x: -x[1])[:5]),
    }


@app.get("/api/stream/logs")
async def stream_logs(log_path: Optional[str] = None):
    """
    Server-Sent Events endpoint — streams new log lines as they appear.
    Connect from frontend with EventSource('/api/stream/logs').
    """
    path = log_path or os.path.join(settings.LOG_WATCH_DIR, "stream.log")

    async def event_generator():
        last_pos = 0
        while True:
            try:
                if os.path.exists(path):
                    with open(path, "r") as f:
                        f.seek(last_pos)
                        new_lines = f.readlines()
                        last_pos  = f.tell()
                    for line in new_lines:
                        data = json.dumps({"line": line.strip(), "timestamp": datetime.now().isoformat()})
                        yield f"data: {data}\n\n"
                await asyncio.sleep(settings.LOG_STREAM_INTERVAL)
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

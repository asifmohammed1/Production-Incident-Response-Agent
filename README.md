# 🚨 Production Incident Response Agent
### Auto-Pilot for Outages — Full Agentic AI System

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    INCIDENT RESPONSE AGENT                       │
├──────────────┬──────────────────┬───────────────────────────────┤
│              │                  │                               │
│  MonitorAgent│  DiagnosisAgent  │    ResponseAgent             │
│              │                  │                               │
│  • PySpark   │  • Ollama LLM    │  • Ollama LLM               │
│  • Pandas    │  • HuggingFace   │  • MCP: Jira ticket         │
│  • HuggingFace│ • MCP: GitHub   │  • MCP: Slack notify        │
│    anomaly   │    deploys       │  • MCP: Incident report      │
│    detection │  • MCP: commits  │                              │
│              │  • MCP: history  │                              │
└──────────────┴──────────────────┴───────────────────────────────┘
         │               │                    │
         └───────────────┴────────────────────┘
                    LangGraph StateGraph
```

---

## Project Structure

```
incident-agent/
├── agents/
│   └── incident_agent.py      # LangGraph multi-agent orchestration
├── api/
│   └── main.py                # FastAPI REST backend
├── config/
│   └── settings.py            # Env-based config
├── dashboard/
│   └── generate_dashboard.py  # HTML dashboard generator
├── data_pipeline/
│   └── spark_log_processor.py # PySpark + Pandas log processing
├── datasets/
│   └── generate_sample_logs.py# Test log data generator
├── mcp_tools/
│   └── mcp_server.py          # MCP tool registry (7 tools)
├── models/
│   ├── anomaly_detector.py    # HuggingFace + keyword anomaly detection
│   └── ollama_client.py       # Ollama LLM client with structured prompts
├── tests/
│   └── test_pipeline.py       # Full end-to-end test suite
├── .env.example               # Environment variable template
├── requirements.txt           # Python dependencies
└── README.md
```

---

## Quick Start

### 1. Clone & Install

```bash
cd incident-agent
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your tokens (all integrations work in mock mode without tokens)
```

### 3. Start Ollama (optional but recommended)

```bash
# Install Ollama from https://ollama.ai
ollama pull llama3.1:latest
ollama serve
```

### 4. Generate Sample Data

```bash
python datasets/generate_sample_logs.py
```

This creates:
- `datasets/sample_logs/normal.log`   — 500 normal log lines
- `datasets/sample_logs/incident.log` — 500 lines with anomaly spike at line 400
- `datasets/sample_logs/stream.log`   — empty file for live streaming

### 5. Run Tests

```bash
python tests/test_pipeline.py
```

### 6. Start the API

```bash
cd api
uvicorn main:app --reload --port 8000
```

### 7. Open Dashboard

```bash
cd dashboard
python generate_dashboard.py
# Then open dashboard/index.html in browser
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/health` | API health + Ollama status |
| POST   | `/api/analyze/sync` | Analyze a log file (synchronous) |
| POST   | `/api/analyze` | Analyze a log file (background) |
| GET    | `/api/incidents` | List all incidents |
| GET    | `/api/incidents/{id}` | Get specific incident |
| GET    | `/api/stats` | Aggregate statistics |
| GET    | `/api/tools` | List MCP tools |
| POST   | `/api/tools/{name}` | Run a specific MCP tool |
| GET    | `/api/stream/logs` | SSE live log stream |

### Example: Analyze logs

```bash
curl -X POST http://localhost:8000/api/analyze/sync \
  -H "Content-Type: application/json" \
  -d '{"log_path": "datasets/sample_logs/incident.log"}'
```

### Example: Run MCP tool

```bash
curl -X POST http://localhost:8000/api/tools/get_service_owners \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"service": "payment-service"}}'
```

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `fetch_recent_logs` | Read last N lines from log file |
| `fetch_deployment_history` | Get recent GitHub deployments |
| `fetch_recent_commits` | Get recent git commits |
| `create_jira_ticket` | Create incident ticket in Jira |
| `notify_slack` | Post alert to Slack channel |
| `query_incident_history` | Search past incidents in DB |
| `get_service_owners` | Look up on-call engineer for a service |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **LLM** | Ollama (Mistral / LLaMA 3 / DeepSeek-Coder) |
| **NLP Models** | HuggingFace sentence-transformers, LogBERT |
| **Agents** | LangGraph (StateGraph) |
| **Data Processing** | PySpark, Pandas |
| **Vector Store** | ChromaDB |
| **API** | FastAPI + Uvicorn |
| **Database** | PostgreSQL (incidents), MongoDB (history) |
| **Integrations** | Slack, Jira, GitHub (via MCP) |
| **Dataset** | Loghub (HDFS), custom synthetic generator |

---

## Intern Work Split

| Intern | Module | Skills Gained |
|--------|--------|---------------|
| Intern 1 | `data_pipeline/` + `datasets/` | PySpark, Pandas, log parsing |
| Intern 2 | `models/` (HuggingFace + Ollama) | LLM, embeddings, anomaly detection |
| Intern 3 | `agents/` (LangGraph) | Multi-agent design, state machines |
| Intern 4 | `mcp_tools/` + `api/` + `dashboard/` | MCP, FastAPI, frontend |

---

## Extending the System

### Add a new MCP tool

```python
# In mcp_tools/mcp_server.py
class MyNewTool(MCPTool):
    name        = "my_tool"
    description = "Does something useful"

    def run(self, param: str) -> Dict[str, Any]:
        return {"result": f"processed {param}"}

# Register in MCPServer._register_all():
MyNewTool,
```

### Add a new agent node

```python
# In agents/incident_agent.py
class MyAgent:
    def run(self, state: IncidentState) -> IncidentState:
        # ... your logic
        return {**state, "my_output": "result", "agent_log": ["MyAgent: done"]}

# Add to graph:
graph.add_node("my_agent", MyAgent().run)
graph.add_edge("response", "my_agent")
```

### Use semantic anomaly detection (GPU recommended)

```python
from models.anomaly_detector import SemanticAnomalyDetector

detector = SemanticAnomalyDetector(model_name="all-MiniLM-L6-v2")
detector.fit(normal_log_messages)   # train on normal logs
detector.score_dataframe(df)        # score new logs
detector.save("./detector_model")   # save for reuse
```

---

## Notes

- **All integrations work in mock mode** without API tokens — great for development
- **Ollama is optional** — falls back to rule-based responses if not running
- **PySpark is optional** — automatically falls back to Pandas if not installed
- **HuggingFace models** download automatically on first use (~100MB)
- For production, replace `incident_store` list in `api/main.py` with MongoDB

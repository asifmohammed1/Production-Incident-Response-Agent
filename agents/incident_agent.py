"""
agents/incident_agent.py

LangGraph Multi-Agent Orchestration for Incident Response.

Three specialized agents running in a directed graph:

  ┌─────────────────┐
  │  MonitorAgent   │ ← watches logs, detects anomaly
  └────────┬────────┘
           │ (anomaly detected)
  ┌────────▼────────┐
  │ DiagnosisAgent  │ ← fetches context, runs root cause via LLM
  └────────┬────────┘
           │
  ┌────────▼────────┐
  │  ResponseAgent  │ ← creates ticket, notifies Slack, drafts report
  └─────────────────┘

State flows through all three agents via a shared IncidentState object.
"""

import os
import sys
import json
from datetime import datetime
from typing import TypedDict, Optional, List, Dict, Any, Annotated
import operator

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from data_pipeline.spark_log_processor import PandasLogProcessor
from models.anomaly_detector import KeywordAnomalyDetector, get_anomaly_detector
from models.ollama_client import ollama_client
from mcp_tools.mcp_server import mcp_server
from config.settings import settings

from loguru import logger

# ── Try importing LangGraph ───────────────────────────────────────────────────
try:
    from langgraph.graph import StateGraph, END
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    logger.warning("LangGraph not available — running in sequential mode")


# ─── Shared State ─────────────────────────────────────────────────────────────

class IncidentState(TypedDict):
    # Input
    log_path:            str
    triggered_at:        str

    # Monitor outputs
    anomaly_detected:    bool
    anomaly_summary:     str
    error_rate:          float
    affected_services:   List[str]
    log_excerpt:         str
    anomaly_logs:        List[Dict]

    # Diagnosis outputs
    recent_deploys:      str
    recent_commits:      str
    past_incidents:      str
    root_cause:          str
    severity:            str

    # Response outputs
    fix_suggestion:      str
    ticket_key:          str
    slack_status:        str
    incident_report:     str
    completed_at:        str

    # Audit trail
    agent_log:           Annotated[List[str], operator.add]


# ─── Agent 1: Monitor Agent ───────────────────────────────────────────────────

class MonitorAgent:
    """
    Watches log files for anomalies using the anomaly detector.
    Produces: anomaly_detected, anomaly_summary, error_rate,
              affected_services, log_excerpt, anomaly_logs
    """

    def __init__(self):
        self.processor = PandasLogProcessor()
        self.detector  = get_anomaly_detector(use_semantic=False)

    def run(self, state: IncidentState) -> IncidentState:
        logger.info("🔍 MonitorAgent starting...")
        log_path = state["log_path"]

        # 1. Load and parse logs
        df = self.processor.load_log_file(log_path)
        if df.empty:
            return {
                **state,
                "anomaly_detected": False,
                "anomaly_summary": "No logs found or log file is empty.",
                "error_rate": 0.0,
                "affected_services": [],
                "log_excerpt": "",
                "anomaly_logs": [],
                "agent_log": ["MonitorAgent: No logs to process"],
            }

        # 2. Detect anomalies
        scored_df    = self.detector.score_dataframe(df)
        anomaly_rows = self.detector.get_top_anomalies(df, top_n=30)
        error_df     = self.processor.extract_error_logs(df, last_n=200)

        # 3. Compute error rate
        total       = len(df)
        error_count = int(df["is_error"].sum())
        error_rate  = error_count / total if total > 0 else 0.0

        anomaly_detected = (
            error_rate >= 0.20 or
            len(anomaly_rows) >= 5 or
            any(lvl in ["FATAL"] for lvl in df["level"].unique())
        )

        # 4. Identify affected services
        if not anomaly_rows.empty and "service" in anomaly_rows.columns:
            affected = anomaly_rows["service"].value_counts().index.tolist()
        elif not error_df.empty:
            affected = error_df["service"].value_counts().index.tolist()
        else:
            affected = []

        # 5. Build log excerpt (last 50 lines)
        log_excerpt = self.processor.get_recent_logs_as_text(df, n=50)

        # 6. Build anomaly summary
        service_summary = self.processor.service_error_summary(df)
        svc_text = service_summary.to_string(index=False) if not service_summary.empty else "N/A"

        anomaly_summary = (
            f"Total log lines: {total}\n"
            f"Error/Fatal lines: {error_count} ({error_rate:.1%})\n"
            f"Anomaly windows detected: {len(anomaly_rows)}\n"
            f"Affected services (by error count):\n{svc_text}\n"
        )

        # 7. Convert anomaly logs to dict list for downstream
        anomaly_log_list = []
        if not anomaly_rows.empty:
            for _, row in anomaly_rows.iterrows():
                anomaly_log_list.append({
                    "timestamp": str(row.get("timestamp", "")),
                    "level":     row.get("level", ""),
                    "service":   row.get("service", ""),
                    "message":   row.get("message", ""),
                    "score":     float(row.get("anomaly_score", 0)),
                })

        logger.info(
            f"MonitorAgent: anomaly={anomaly_detected}, "
            f"error_rate={error_rate:.1%}, affected={affected}"
        )

        return {
            **state,
            "anomaly_detected":  anomaly_detected,
            "anomaly_summary":   anomaly_summary,
            "error_rate":        error_rate,
            "affected_services": affected[:5],
            "log_excerpt":       log_excerpt,
            "anomaly_logs":      anomaly_log_list,
            "agent_log":         [
                f"MonitorAgent [{datetime.now().strftime('%H:%M:%S')}]: "
                f"Detected anomaly={anomaly_detected}, error_rate={error_rate:.1%}, "
                f"affected_services={affected[:3]}"
            ],
        }


# ─── Agent 2: Diagnosis Agent ─────────────────────────────────────────────────

class DiagnosisAgent:
    """
    Gathers context via MCP tools, then uses Ollama LLM to
    identify root cause and classify severity.

    Produces: recent_deploys, recent_commits, past_incidents,
              root_cause, severity
    """

    def run(self, state: IncidentState) -> IncidentState:
        logger.info("🧠 DiagnosisAgent starting...")

        primary_service = (
            state["affected_services"][0]
            if state["affected_services"]
            else "unknown-service"
        )

        # 1. Gather context via MCP tools (parallel in production — sequential here)
        deploys_raw  = mcp_server.run("fetch_deployment_history", hours_back=24)
        commits_raw  = mcp_server.run("fetch_recent_commits", n_commits=8)
        history_raw  = mcp_server.run("query_incident_history", service=primary_service, days_back=30)

        # 2. Format context as readable strings for LLM
        recent_deploys = self._format_deploys(deploys_raw)
        recent_commits = self._format_commits(commits_raw)
        past_incidents = self._format_history(history_raw)

        # 3. LLM root cause analysis
        logger.info("DiagnosisAgent: Calling Ollama for root cause analysis...")
        root_cause = ollama_client.analyze_root_cause(
            log_excerpt    = state["log_excerpt"],
            anomaly_summary= state["anomaly_summary"],
            recent_deploys = recent_deploys,
            recent_commits = recent_commits,
            past_incidents = past_incidents,
        )

        # 4. LLM severity classification
        severity = ollama_client.classify_severity(
            anomaly_summary  = state["anomaly_summary"],
            error_rate       = state["error_rate"],
            affected_services= state["affected_services"],
        )

        logger.info(f"DiagnosisAgent: severity={severity.split()[0]}")

        return {
            **state,
            "recent_deploys": recent_deploys,
            "recent_commits": recent_commits,
            "past_incidents": past_incidents,
            "root_cause":     root_cause,
            "severity":       severity,
            "agent_log":      [
                f"DiagnosisAgent [{datetime.now().strftime('%H:%M:%S')}]: "
                f"Root cause identified. Severity: {severity[:30]}"
            ],
        }

    def _format_deploys(self, raw: dict) -> str:
        deploys = raw.get("deployments", [])
        if not deploys:
            return "No recent deployments found."
        lines = []
        for d in deploys:
            lines.append(
                f"• [{d.get('created_at', 'unknown')}] "
                f"{d.get('description', 'No description')} "
                f"by {d.get('creator', {}).get('login', 'unknown')} "
                f"(SHA: {d.get('sha', 'N/A')[:8]})"
            )
        return "\n".join(lines)

    def _format_commits(self, raw: dict) -> str:
        commits = raw.get("commits", [])
        if not commits:
            return "No recent commits found."
        lines = []
        for c in commits:
            lines.append(
                f"• [{c.get('date', '')[:16]}] "
                f"{c.get('sha', 'N/A')[:8]} — {c.get('message', '')} "
                f"by {c.get('author', 'unknown')}"
            )
        return "\n".join(lines)

    def _format_history(self, raw: dict) -> str:
        incidents = raw.get("incidents", [])
        if not incidents:
            return "No similar past incidents found."
        lines = []
        for i in incidents:
            lines.append(
                f"• {i.get('incident_id')} [{i.get('severity')}] "
                f"{i.get('service')} — Cause: {i.get('root_cause', 'N/A')[:60]} "
                f"| Fix: {i.get('resolution', 'N/A')[:60]}"
            )
        return "\n".join(lines)


# ─── Agent 3: Response Agent ──────────────────────────────────────────────────

class ResponseAgent:
    """
    Takes the diagnosis and takes action:
    1. Suggests a fix via Ollama
    2. Creates Jira incident ticket via MCP
    3. Notifies Slack via MCP
    4. Drafts a full incident report via Ollama

    Produces: fix_suggestion, ticket_key, slack_status,
              incident_report, completed_at
    """

    def run(self, state: IncidentState) -> IncidentState:
        logger.info("🚨 ResponseAgent starting...")

        primary_service = (
            state["affected_services"][0]
            if state["affected_services"]
            else "unknown-service"
        )

        # 1. Get past resolutions for fix context
        past_resolutions = "\n".join([
            i.get("resolution", "")
            for i in json.loads(
                json.dumps(
                    mcp_server.run("query_incident_history", service=primary_service)
                    .get("incidents", [])
                )
            )
        ]) or "No past resolutions available."

        # 2. LLM fix suggestion
        logger.info("ResponseAgent: Generating fix suggestions...")
        fix_suggestion = ollama_client.suggest_fix(
            root_cause       = state["root_cause"],
            service          = primary_service,
            past_resolutions = past_resolutions,
        )

        # 3. Get service owner
        owner = mcp_server.run("get_service_owners", service=primary_service)

        # 4. Create Jira ticket
        severity_label = state["severity"].split()[0] if state["severity"] else "High"
        ticket_result  = mcp_server.run(
            "create_jira_ticket",
            summary     = f"[{severity_label}] Production incident — {primary_service}",
            description = (
                f"Detected at: {state['triggered_at']}\n\n"
                f"Anomaly Summary:\n{state['anomaly_summary']}\n\n"
                f"Root Cause:\n{state['root_cause'][:500]}"
            ),
            severity    = severity_label,
            assignee    = owner.get("oncall", ""),
        )
        ticket_key = ticket_result.get("ticket_key", "INC-???")

        # 5. Notify Slack
        slack_message = (
            f"*Production Incident Detected* — `{primary_service}`\n"
            f"*Severity:* {severity_label}\n"
            f"*Ticket:* {ticket_key}\n"
            f"*Owner:* {owner.get('slack', '@oncall')}\n"
            f"*Error Rate:* {state['error_rate']:.1%}\n"
            f"*Root Cause (brief):* {state['root_cause'][:200]}...\n"
            f"*Immediate Action:* {fix_suggestion[:200]}..."
        )
        slack_result = mcp_server.run(
            "notify_slack",
            message  = slack_message,
            severity = severity_label.lower(),
        )

        # 6. Draft incident report
        logger.info("ResponseAgent: Drafting incident report...")
        incident_report = ollama_client.draft_incident_report(
            severity         = severity_label,
            root_cause       = state["root_cause"],
            fix              = fix_suggestion,
            timeline         = f"Detected: {state['triggered_at']} | Ticket: {ticket_key}",
            affected_services= state["affected_services"],
            ticket_key       = ticket_key,
        )

        completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"ResponseAgent: Done. Ticket={ticket_key}, Slack={slack_result.get('status')}")

        return {
            **state,
            "fix_suggestion":  fix_suggestion,
            "ticket_key":      ticket_key,
            "slack_status":    slack_result.get("status", "unknown"),
            "incident_report": incident_report,
            "completed_at":    completed_at,
            "agent_log":       [
                f"ResponseAgent [{completed_at}]: "
                f"Ticket={ticket_key}, Slack={slack_result.get('status')}, "
                f"Owner={owner.get('oncall', 'unknown')}"
            ],
        }


# ─── Graph Orchestration ──────────────────────────────────────────────────────

def should_diagnose(state: IncidentState) -> str:
    """Conditional edge: only run diagnosis if anomaly was detected."""
    return "diagnosis" if state.get("anomaly_detected") else END


def build_agent_graph():
    """Build and compile the LangGraph agent pipeline."""
    if not LANGGRAPH_AVAILABLE:
        return None

    monitor_agent   = MonitorAgent()
    diagnosis_agent = DiagnosisAgent()
    response_agent  = ResponseAgent()

    graph = StateGraph(IncidentState)

    graph.add_node("monitor",   monitor_agent.run)
    graph.add_node("diagnosis", diagnosis_agent.run)
    graph.add_node("response",  response_agent.run)

    graph.set_entry_point("monitor")
    graph.add_conditional_edges("monitor", should_diagnose)
    graph.add_edge("diagnosis", "response")
    graph.add_edge("response",  END)

    return graph.compile()


# ─── Sequential fallback (no LangGraph) ─────────────────────────────────────

class SequentialIncidentPipeline:
    """Runs the three agents in sequence when LangGraph is unavailable."""

    def __init__(self):
        self.monitor   = MonitorAgent()
        self.diagnosis = DiagnosisAgent()
        self.response  = ResponseAgent()

    def run(self, log_path: str) -> IncidentState:
        state: IncidentState = {
            "log_path":          log_path,
            "triggered_at":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "anomaly_detected":  False,
            "anomaly_summary":   "",
            "error_rate":        0.0,
            "affected_services": [],
            "log_excerpt":       "",
            "anomaly_logs":      [],
            "recent_deploys":    "",
            "recent_commits":    "",
            "past_incidents":    "",
            "root_cause":        "",
            "severity":          "",
            "fix_suggestion":    "",
            "ticket_key":        "",
            "slack_status":      "",
            "incident_report":   "",
            "completed_at":      "",
            "agent_log":         [],
        }

        state = self.monitor.run(state)

        if not state["anomaly_detected"]:
            logger.info("No anomaly detected — pipeline complete.")
            return state

        state = self.diagnosis.run(state)
        state = self.response.run(state)
        return state


# ─── Public entry point ───────────────────────────────────────────────────────

def run_incident_pipeline(log_path: str) -> IncidentState:
    """
    Main entry point. Uses LangGraph if available, else sequential.
    Returns the final IncidentState with all outputs.
    """
    graph = build_agent_graph()

    if graph and LANGGRAPH_AVAILABLE:
        logger.info("Running via LangGraph...")
        initial_state: IncidentState = {
            "log_path":          log_path,
            "triggered_at":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "anomaly_detected":  False,
            "anomaly_summary":   "",
            "error_rate":        0.0,
            "affected_services": [],
            "log_excerpt":       "",
            "anomaly_logs":      [],
            "recent_deploys":    "",
            "recent_commits":    "",
            "past_incidents":    "",
            "root_cause":        "",
            "severity":          "",
            "fix_suggestion":    "",
            "ticket_key":        "",
            "slack_status":      "",
            "incident_report":   "",
            "completed_at":      "",
            "agent_log":         [],
        }
        return graph.invoke(initial_state)
    else:
        logger.info("Running via sequential pipeline...")
        pipeline = SequentialIncidentPipeline()
        return pipeline.run(log_path)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")

    # Generate test data
    from datasets.generate_sample_logs import generate_incident_log
    generate_incident_log()

    log_file = "datasets/sample_logs/incident.log"
    logger.info(f"Starting incident pipeline on: {log_file}")

    result = run_incident_pipeline(log_file)

    print("\n" + "═" * 60)
    print("INCIDENT PIPELINE COMPLETE")
    print("═" * 60)
    print(f"Anomaly Detected : {result['anomaly_detected']}")
    print(f"Error Rate       : {result['error_rate']:.1%}")
    print(f"Affected Services: {result['affected_services']}")
    print(f"Severity         : {result['severity'][:50]}")
    print(f"Ticket           : {result['ticket_key']}")
    print(f"Slack Status     : {result['slack_status']}")
    print(f"\nROOT CAUSE:\n{result['root_cause'][:400]}")
    print(f"\nFIX SUGGESTION:\n{result['fix_suggestion'][:400]}")
    print(f"\nINCIDENT REPORT:\n{result['incident_report'][:600]}")
    print(f"\nAGENT LOG:")
    for entry in result["agent_log"]:
        print(f"  {entry}")

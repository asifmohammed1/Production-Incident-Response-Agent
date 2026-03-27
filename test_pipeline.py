"""
tests/test_pipeline.py

End-to-end tests for all pipeline components.
Run with: python tests/test_pipeline.py
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

console = Console()

def test_log_generation():
    console.rule("[bold orange]Test 1: Log Generation")
    from datasets.generate_sample_logs import generate_normal_log, generate_incident_log, generate_streaming_log
    generate_normal_log()
    generate_incident_log()
    generate_streaming_log()
    assert os.path.exists("datasets/sample_logs/normal.log")
    assert os.path.exists("datasets/sample_logs/incident.log")
    console.print("✅ Log generation [green]PASSED[/green]")

def test_log_processor():
    console.rule("[bold orange]Test 2: Log Processor (Pandas)")
    from data_pipeline.spark_log_processor import PandasLogProcessor
    proc = PandasLogProcessor()
    df   = proc.load_log_file("datasets/sample_logs/incident.log")
    assert len(df) > 0, "DataFrame is empty"
    assert "level" in df.columns
    assert "is_error" in df.columns

    err_rate = df["is_error"].mean()
    anomalies = proc.detect_anomaly_windows(df)
    svc_summary = proc.service_error_summary(df)

    table = Table(title="Log Processor Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Value",  style="green")
    table.add_row("Total log lines",    str(len(df)))
    table.add_row("Error rate",         f"{err_rate:.1%}")
    table.add_row("Anomaly windows",    str(len(anomalies)))
    table.add_row("Services with errors", str(len(svc_summary)))
    console.print(table)
    console.print("✅ Log processor [green]PASSED[/green]")

def test_anomaly_detector():
    console.rule("[bold orange]Test 3: Anomaly Detector")
    from data_pipeline.spark_log_processor import PandasLogProcessor
    from models.anomaly_detector import KeywordAnomalyDetector

    proc     = PandasLogProcessor()
    df       = proc.load_log_file("datasets/sample_logs/incident.log")
    detector = KeywordAnomalyDetector()
    scored   = detector.score_dataframe(df)
    top      = detector.get_top_anomalies(df, top_n=5)

    assert "anomaly_score" in scored.columns
    assert "is_anomaly" in scored.columns

    console.print(f"Total anomalies: [red]{scored['is_anomaly'].sum()}[/red] / {len(scored)}")
    if not top.empty:
        console.print("\nTop anomalous lines:")
        for _, row in top.iterrows():
            console.print(f"  [{row['level']}] {row['service']}: {row['message'][:60]}... (score={row['anomaly_score']:.2f})")
    console.print("✅ Anomaly detector [green]PASSED[/green]")

def test_mcp_server():
    console.rule("[bold orange]Test 4: MCP Server")
    from mcp_tools.mcp_server import mcp_server

    tools = mcp_server.list_tools()
    assert len(tools) >= 6, f"Expected 6+ tools, got {len(tools)}"

    console.print(f"Registered tools: [cyan]{len(tools)}[/cyan]")
    for t in tools:
        console.print(f"  • [bold]{t['name']}[/bold]")

    # Test each tool
    r1 = mcp_server.run("fetch_deployment_history", hours_back=24)
    assert "deployments" in r1
    console.print(f"  fetch_deployment_history → {r1['count']} deployments ✓")

    r2 = mcp_server.run("get_service_owners", service="payment-service")
    assert "oncall" in r2
    console.print(f"  get_service_owners → {r2['oncall']} ✓")

    r3 = mcp_server.run("query_incident_history", service="payment", days_back=30)
    assert "incidents" in r3
    console.print(f"  query_incident_history → {r3['count']} incidents ✓")

    r4 = mcp_server.run("create_jira_ticket", summary="Test incident", description="Test", severity="High")
    assert "ticket_key" in r4
    console.print(f"  create_jira_ticket → {r4['ticket_key']} ✓")

    console.print("✅ MCP server [green]PASSED[/green]")

def test_ollama_client():
    console.rule("[bold orange]Test 5: Ollama Client")
    from models.ollama_client import ollama_client

    console.print(f"Ollama available: [{'green' if ollama_client._available else 'yellow'}]{ollama_client._available}[/]")
    console.print(f"Model: [cyan]{ollama_client.model}[/cyan]")

    sev = ollama_client.classify_severity(
        "Multiple FATAL errors, connection pool exhausted",
        error_rate=0.45,
        affected_services=["payment-service"],
    )
    console.print(f"Severity classification: [yellow]{sev[:80]}[/yellow]")
    console.print("✅ Ollama client [green]PASSED[/green]")

def test_full_pipeline():
    console.rule("[bold orange]Test 6: Full Agent Pipeline (End-to-End)")
    from agents.incident_agent import run_incident_pipeline

    log_path = "datasets/sample_logs/incident.log"
    console.print(f"Running pipeline on: [cyan]{log_path}[/cyan]")

    result = run_incident_pipeline(log_path)

    assert "anomaly_detected" in result
    assert "agent_log" in result

    panel_text = (
        f"[bold]Anomaly Detected:[/bold] {result['anomaly_detected']}\n"
        f"[bold]Error Rate:[/bold] {result['error_rate']:.1%}\n"
        f"[bold]Affected Services:[/bold] {result['affected_services']}\n"
        f"[bold]Severity:[/bold] {result['severity'][:60]}\n"
        f"[bold]Ticket:[/bold] {result['ticket_key']}\n"
        f"[bold]Slack:[/bold] {result['slack_status']}\n"
        f"\n[bold]Root Cause (excerpt):[/bold]\n{result['root_cause'][:300]}\n"
        f"\n[bold]Fix (excerpt):[/bold]\n{result['fix_suggestion'][:300]}\n"
        f"\n[bold]Agent Log:[/bold]\n" + "\n".join(result['agent_log'])
    )
    console.print(Panel(panel_text, title="Pipeline Result", border_style="orange1"))
    console.print("✅ Full pipeline [green]PASSED[/green]")
    return result

def run_all_tests():
    console.print(Panel.fit(
        "[bold orange]🚨 Incident Response Agent — Test Suite[/bold orange]\n"
        "[dim]Testing all pipeline components end-to-end[/dim]",
        border_style="orange1"
    ))

    tests = [
        test_log_generation,
        test_log_processor,
        test_anomaly_detector,
        test_mcp_server,
        test_ollama_client,
        test_full_pipeline,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            console.print(f"❌ [red]FAILED: {e}[/red]")
            failed += 1

    console.print()
    console.print(Panel.fit(
        f"[green]Passed: {passed}[/green]  [red]Failed: {failed}[/red]  Total: {len(tests)}",
        title="Test Results",
        border_style="green" if failed == 0 else "red"
    ))

if __name__ == "__main__":
    run_all_tests()

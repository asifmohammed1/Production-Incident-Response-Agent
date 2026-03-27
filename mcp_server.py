"""
mcp_tools/mcp_server.py

MCP (Model Context Protocol) Tool Server
Exposes all external integrations as structured tools
that LangChain/LangGraph agents can call.

Tools exposed:
  - fetch_recent_logs       → Read last N lines from log file
  - fetch_deployment_history→ Get recent deployments from GitHub
  - fetch_recent_commits    → Get recent commits from GitHub
  - create_jira_ticket      → Create incident ticket in Jira
  - notify_slack            → Post alert to Slack channel
  - query_incident_history  → Search past incidents in MongoDB
  - get_service_owners      → Look up who owns a service
"""

import os
import sys
import json
import httpx
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config.settings import settings


# ─── Base tool interface ───────────────────────────────────────────────────────

class MCPTool:
    name: str        = "base_tool"
    description: str = "Base MCP tool"

    def run(self, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError


# ─── Tool 1: Fetch Recent Logs ────────────────────────────────────────────────

class FetchRecentLogsTool(MCPTool):
    name        = "fetch_recent_logs"
    description = (
        "Fetch the last N lines from the application log file. "
        "Use this to get raw context when investigating an incident."
    )

    def run(self, log_path: str = None, n_lines: int = 100) -> Dict[str, Any]:
        path = log_path or os.path.join(settings.LOG_WATCH_DIR, "stream.log")
        if not os.path.exists(path):
            return {"error": f"Log file not found: {path}", "lines": []}
        with open(path, "r") as f:
            all_lines = f.readlines()
        recent = all_lines[-n_lines:]
        logger.info(f"[MCP] fetch_recent_logs → {len(recent)} lines from {path}")
        return {
            "log_path": path,
            "total_lines": len(all_lines),
            "returned_lines": len(recent),
            "content": "".join(recent),
        }


# ─── Tool 2: Fetch Deployment History ────────────────────────────────────────

class FetchDeploymentHistoryTool(MCPTool):
    name        = "fetch_deployment_history"
    description = (
        "Fetch recent GitHub deployment history for the repository. "
        "Use this to correlate incidents with recent deploys."
    )

    def run(self, hours_back: int = 24) -> Dict[str, Any]:
        if not settings.GITHUB_TOKEN or not settings.GITHUB_REPO:
            return self._mock_deployments(hours_back)

        url     = f"https://api.github.com/repos/{settings.GITHUB_REPO}/deployments"
        headers = {
            "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        try:
            resp = httpx.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            deploys = resp.json()
            cutoff  = datetime.utcnow() - timedelta(hours=hours_back)
            recent  = [
                d for d in deploys
                if datetime.strptime(d["created_at"], "%Y-%m-%dT%H:%M:%SZ") > cutoff
            ]
            logger.info(f"[MCP] fetch_deployment_history → {len(recent)} deployments")
            return {"deployments": recent, "count": len(recent)}
        except Exception as e:
            logger.error(f"[MCP] GitHub deployment fetch failed: {e}")
            return self._mock_deployments(hours_back)

    def _mock_deployments(self, hours_back: int) -> Dict[str, Any]:
        """Return realistic mock data when GitHub token is not configured."""
        now = datetime.utcnow()
        return {
            "deployments": [
                {
                    "id": 1001,
                    "sha": "a1b2c3d4",
                    "ref": "main",
                    "environment": "production",
                    "created_at": (now - timedelta(hours=2)).isoformat(),
                    "creator": {"login": "dev-alice"},
                    "description": "Release v2.4.1 — payment service refactor",
                },
                {
                    "id": 1000,
                    "sha": "e5f6a7b8",
                    "ref": "main",
                    "environment": "production",
                    "created_at": (now - timedelta(hours=18)).isoformat(),
                    "creator": {"login": "dev-bob"},
                    "description": "Hotfix: auth token expiry bug",
                },
            ],
            "count": 2,
            "note": "Mock data — configure GITHUB_TOKEN for live data",
        }


# ─── Tool 3: Fetch Recent Commits ─────────────────────────────────────────────

class FetchRecentCommitsTool(MCPTool):
    name        = "fetch_recent_commits"
    description = (
        "Fetch recent git commits from the repository. "
        "Use this to identify what code changed before an incident."
    )

    def run(self, n_commits: int = 10) -> Dict[str, Any]:
        if not settings.GITHUB_TOKEN or not settings.GITHUB_REPO:
            return self._mock_commits(n_commits)

        url     = f"https://api.github.com/repos/{settings.GITHUB_REPO}/commits"
        headers = {
            "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        try:
            resp = httpx.get(url, headers=headers, params={"per_page": n_commits}, timeout=10)
            resp.raise_for_status()
            commits = resp.json()
            logger.info(f"[MCP] fetch_recent_commits → {len(commits)} commits")
            return {
                "commits": [
                    {
                        "sha":     c["sha"][:8],
                        "message": c["commit"]["message"].split("\n")[0],
                        "author":  c["commit"]["author"]["name"],
                        "date":    c["commit"]["author"]["date"],
                    }
                    for c in commits
                ]
            }
        except Exception as e:
            logger.error(f"[MCP] GitHub commit fetch failed: {e}")
            return self._mock_commits(n_commits)

    def _mock_commits(self, n: int) -> Dict[str, Any]:
        now = datetime.utcnow()
        return {
            "commits": [
                {"sha": "a1b2c3d4", "message": "refactor: PaymentProcessor retry logic", "author": "alice", "date": (now - timedelta(hours=2)).isoformat()},
                {"sha": "e5f6a7b8", "message": "fix: connection pool max size increased", "author": "bob",   "date": (now - timedelta(hours=5)).isoformat()},
                {"sha": "c9d0e1f2", "message": "feat: new auth middleware added",         "author": "carol", "date": (now - timedelta(hours=9)).isoformat()},
                {"sha": "g3h4i5j6", "message": "chore: updated logging configuration",   "author": "dave",  "date": (now - timedelta(hours=20)).isoformat()},
            ][:n],
            "note": "Mock data — configure GITHUB_TOKEN for live data",
        }


# ─── Tool 4: Create Jira Ticket ───────────────────────────────────────────────

class CreateJiraTicketTool(MCPTool):
    name        = "create_jira_ticket"
    description = (
        "Create a Jira incident ticket with summary, description, severity, and assignee. "
        "Use this to formally log an incident."
    )

    def run(
        self,
        summary: str,
        description: str,
        severity: str = "High",
        assignee: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not settings.JIRA_API_TOKEN:
            return self._mock_ticket(summary, severity)

        url     = f"{settings.JIRA_BASE_URL}/rest/api/3/issue"
        headers = {"Content-Type": "application/json"}
        auth    = (settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)
        payload = {
            "fields": {
                "project":     {"key": settings.JIRA_PROJECT_KEY},
                "summary":     summary,
                "description": {
                    "type": "doc", "version": 1,
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}]
                },
                "issuetype":   {"name": "Incident"},
                "priority":    {"name": severity},
            }
        }
        try:
            resp = httpx.post(url, headers=headers, auth=auth, json=payload, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            ticket_key = data.get("key", "INC-???")
            logger.info(f"[MCP] Jira ticket created: {ticket_key}")
            return {"ticket_key": ticket_key, "url": f"{settings.JIRA_BASE_URL}/browse/{ticket_key}"}
        except Exception as e:
            logger.error(f"[MCP] Jira ticket creation failed: {e}")
            return self._mock_ticket(summary, severity)

    def _mock_ticket(self, summary: str, severity: str) -> Dict[str, Any]:
        ticket_num = f"INC-{datetime.now().strftime('%H%M%S')}"
        return {
            "ticket_key": ticket_num,
            "url": f"https://yourcompany.atlassian.net/browse/{ticket_num}",
            "summary": summary,
            "severity": severity,
            "note": "Mock ticket — configure JIRA_API_TOKEN for live data",
        }


# ─── Tool 5: Notify Slack ─────────────────────────────────────────────────────

class NotifySlackTool(MCPTool):
    name        = "notify_slack"
    description = (
        "Post an incident alert to the Slack channel. "
        "Use this to notify the on-call team immediately."
    )

    def run(self, message: str, severity: str = "high") -> Dict[str, Any]:
        if not settings.SLACK_BOT_TOKEN:
            logger.info(f"[MCP] Slack (mock) → {message[:80]}...")
            return {"status": "mock_sent", "channel": settings.SLACK_ALERT_CHANNEL}

        emoji   = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
        payload = {
            "channel": settings.SLACK_ALERT_CHANNEL,
            "text":    f"{emoji} *INCIDENT ALERT* [{severity.upper()}]\n{message}",
        }
        headers = {
            "Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}",
            "Content-Type":  "application/json",
        }
        try:
            resp = httpx.post("https://slack.com/api/chat.postMessage", headers=headers, json=payload, timeout=10)
            data = resp.json()
            if data.get("ok"):
                logger.info(f"[MCP] Slack notification sent to {settings.SLACK_ALERT_CHANNEL}")
                return {"status": "sent", "ts": data.get("ts"), "channel": data.get("channel")}
            else:
                return {"status": "failed", "error": data.get("error")}
        except Exception as e:
            logger.error(f"[MCP] Slack notification failed: {e}")
            return {"status": "error", "error": str(e)}


# ─── Tool 6: Query Incident History ───────────────────────────────────────────

class QueryIncidentHistoryTool(MCPTool):
    name        = "query_incident_history"
    description = (
        "Search past incident records from the database. "
        "Use this to find similar past incidents and their resolutions."
    )

    def run(self, service: Optional[str] = None, days_back: int = 30, limit: int = 5) -> Dict[str, Any]:
        """
        In production this queries MongoDB.
        Here we return a realistic mock response.
        """
        mock_incidents = [
            {
                "incident_id": "INC-2024-0912",
                "timestamp": (datetime.utcnow() - timedelta(days=15)).isoformat(),
                "service": "payment-service",
                "root_cause": "Connection pool exhaustion due to slow DB queries",
                "resolution": "Increased pool size from 10 to 50, added query timeout of 5s",
                "duration_minutes": 45,
                "severity": "High",
            },
            {
                "incident_id": "INC-2024-0830",
                "timestamp": (datetime.utcnow() - timedelta(days=28)).isoformat(),
                "service": "auth-service",
                "root_cause": "Memory leak in token validation middleware",
                "resolution": "Rolled back auth middleware to v1.2.3, patched in v1.2.4",
                "duration_minutes": 22,
                "severity": "Critical",
            },
            {
                "incident_id": "INC-2024-0801",
                "timestamp": (datetime.utcnow() - timedelta(days=45)).isoformat(),
                "service": "api-gateway",
                "root_cause": "Upstream timeout cascade from payment-service",
                "resolution": "Added circuit breaker, increased timeout threshold",
                "duration_minutes": 60,
                "severity": "High",
            },
        ]

        if service:
            filtered = [i for i in mock_incidents if service.lower() in i["service"]]
        else:
            filtered = mock_incidents

        logger.info(f"[MCP] query_incident_history → {len(filtered[:limit])} results")
        return {
            "incidents": filtered[:limit],
            "count": len(filtered[:limit]),
            "note": "Mock data — connect MongoDB for live incident history",
        }


# ─── Tool 7: Get Service Owners ───────────────────────────────────────────────

class GetServiceOwnersTool(MCPTool):
    name        = "get_service_owners"
    description = (
        "Look up the on-call engineer and team for a given service. "
        "Use this to know who to notify or assign the incident to."
    )

    # In production: query a CMDB or PagerDuty
    SERVICE_OWNERS = {
        "auth-service":         {"team": "Identity",  "oncall": "alice@company.com",   "slack": "@alice"},
        "payment-service":      {"team": "Payments",  "oncall": "bob@company.com",     "slack": "@bob"},
        "api-gateway":          {"team": "Platform",  "oncall": "carol@company.com",   "slack": "@carol"},
        "db-connector":         {"team": "Data",      "oncall": "dave@company.com",    "slack": "@dave"},
        "notification-service": {"team": "Comms",     "oncall": "eve@company.com",     "slack": "@eve"},
    }

    def run(self, service: str) -> Dict[str, Any]:
        owner = self.SERVICE_OWNERS.get(service.lower(), {
            "team": "Platform", "oncall": "oncall@company.com", "slack": "@oncall"
        })
        logger.info(f"[MCP] get_service_owners({service}) → {owner['oncall']}")
        return {"service": service, **owner}


# ─── MCP Server Registry ──────────────────────────────────────────────────────

class MCPServer:
    """
    Registry of all MCP tools.
    Agents call server.run(tool_name, **kwargs) to invoke any tool.
    """

    def __init__(self):
        self.tools: Dict[str, MCPTool] = {}
        self._register_all()

    def _register_all(self):
        for cls in [
            FetchRecentLogsTool,
            FetchDeploymentHistoryTool,
            FetchRecentCommitsTool,
            CreateJiraTicketTool,
            NotifySlackTool,
            QueryIncidentHistoryTool,
            GetServiceOwnersTool,
        ]:
            tool = cls()
            self.tools[tool.name] = tool
        logger.info(f"[MCP] Registered {len(self.tools)} tools: {list(self.tools.keys())}")

    def run(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        if tool_name not in self.tools:
            return {"error": f"Unknown tool: {tool_name}. Available: {list(self.tools.keys())}"}
        logger.info(f"[MCP] Running tool: {tool_name} with args: {kwargs}")
        return self.tools[tool_name].run(**kwargs)

    def list_tools(self) -> List[Dict[str, str]]:
        return [{"name": t.name, "description": t.description} for t in self.tools.values()]


# Singleton instance
mcp_server = MCPServer()


if __name__ == "__main__":
    print("\n🔧 MCP Server — Tool Test\n")
    print("Available tools:")
    for t in mcp_server.list_tools():
        print(f"  • {t['name']}: {t['description'][:60]}...")

    print("\n--- fetch_recent_logs ---")
    print(mcp_server.run("fetch_recent_logs", n_lines=5))

    print("\n--- fetch_deployment_history ---")
    result = mcp_server.run("fetch_deployment_history", hours_back=24)
    print(json.dumps(result, indent=2, default=str))

    print("\n--- get_service_owners ---")
    print(mcp_server.run("get_service_owners", service="payment-service"))

    print("\n--- query_incident_history ---")
    result = mcp_server.run("query_incident_history", service="payment", days_back=30)
    print(json.dumps(result, indent=2, default=str))

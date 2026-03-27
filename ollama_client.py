"""
models/ollama_client.py

Ollama LLM client — handles all LLM calls with
structured prompts for each agent task:
  - Root cause analysis
  - Fix suggestion generation
  - Incident report drafting
  - Severity classification
"""

import httpx
import json
from typing import Optional
from loguru import logger

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config.settings import settings


class OllamaClient:
    """
    Thin wrapper around Ollama's REST API.
    Falls back to a rule-based response if Ollama is unavailable.
    """

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model    = settings.OLLAMA_MODEL
        self._available = self._check_availability()

    def _check_availability(self) -> bool:
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=3)
            if resp.status_code == 200:
                logger.info(f"Ollama available at {self.base_url} — model: {self.model}")
                return True
        except Exception:
            pass
        logger.warning("Ollama not available — using rule-based fallback responses")
        return False

    def generate(self, prompt: str, system: str = "", max_tokens: int = 1024) -> str:
        """Send a prompt to Ollama and return the response text."""
        if not self._available:
            return self._rule_based_fallback(prompt)

        payload = {
            "model":  self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.3},
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except Exception as e:
            logger.error(f"Ollama generation failed: {e}")
            return self._rule_based_fallback(prompt)

    def _rule_based_fallback(self, prompt: str) -> str:
        """Deterministic fallback when Ollama is unavailable."""
        return (
            "[LLM Fallback — Ollama not running]\n"
            "Based on the error patterns detected:\n"
            "• Check service logs for connection/timeout errors\n"
            "• Review recent deployments for code changes\n"
            "• Verify database and upstream service health\n"
            "• Consider rolling back the most recent deployment\n"
            "• Escalate to on-call engineer if unresolved within 15 minutes."
        )

    # ── Specialized prompt methods ─────────────────────────────────────────────

    def analyze_root_cause(
        self,
        log_excerpt: str,
        anomaly_summary: str,
        recent_deploys: str,
        recent_commits: str,
        past_incidents: str,
    ) -> str:
        system = (
            "You are a senior site reliability engineer (SRE) with 10+ years of experience. "
            "You analyze production incidents with precision. "
            "Be concise, technical, and actionable. Never guess — base analysis on evidence."
        )
        prompt = f"""
TASK: Identify the root cause of this production incident.

=== ANOMALY SUMMARY ===
{anomaly_summary}

=== RECENT LOG EXCERPT (last 50 lines) ===
{log_excerpt}

=== RECENT DEPLOYMENTS (last 24h) ===
{recent_deploys}

=== RECENT COMMITS ===
{recent_commits}

=== SIMILAR PAST INCIDENTS ===
{past_incidents}

Based on this evidence, provide:
1. ROOT CAUSE: What specifically caused this incident?
2. CONTRIBUTING FACTORS: What made it worse?
3. CONFIDENCE: How confident are you? (High/Medium/Low) and why?
4. TIMELINE: When did the issue likely start and why?

Be specific. Reference log lines, commit SHAs, or deployment IDs where relevant.
"""
        return self.generate(prompt, system)

    def suggest_fix(
        self,
        root_cause: str,
        service: str,
        past_resolutions: str,
    ) -> str:
        system = (
            "You are an expert SRE providing actionable remediation steps. "
            "Give specific, ordered steps that an on-call engineer can follow immediately. "
            "Prioritize fastest path to service restoration, then permanent fix."
        )
        prompt = f"""
TASK: Suggest a fix for this production incident.

=== ROOT CAUSE ===
{root_cause}

=== AFFECTED SERVICE ===
{service}

=== HOW SIMILAR PAST INCIDENTS WERE RESOLVED ===
{past_resolutions}

Provide:
1. IMMEDIATE ACTIONS (next 5 minutes): Steps to stop the bleeding
2. SHORT-TERM FIX (next 30 minutes): Restore service stability  
3. PERMANENT FIX (next sprint): Prevent recurrence
4. ROLLBACK RECOMMENDATION: Should we roll back? If yes, to which version?
5. RISK: What could go wrong with the fix?

Format as numbered steps. Be specific and actionable.
"""
        return self.generate(prompt, system)

    def classify_severity(self, anomaly_summary: str, error_rate: float, affected_services: list) -> str:
        prompt = f"""
Classify the severity of this incident on a scale: Critical / High / Medium / Low.

Error rate: {error_rate:.1%}
Affected services: {', '.join(affected_services)}
Anomaly details: {anomaly_summary}

Rules:
- Critical: >50% error rate OR multiple core services down OR payment/auth affected
- High: 20-50% error rate OR single core service degraded
- Medium: 5-20% error rate OR non-critical service affected
- Low: <5% error rate OR isolated errors

Respond with ONLY: Critical, High, Medium, or Low — then one sentence explanation.
"""
        return self.generate(prompt)

    def draft_incident_report(
        self,
        severity: str,
        root_cause: str,
        fix: str,
        timeline: str,
        affected_services: list,
        ticket_key: str,
    ) -> str:
        system = (
            "You are a technical writer creating a clear incident report. "
            "Use professional language. Be factual and precise. "
            "The audience is engineering leadership and the on-call team."
        )
        prompt = f"""
Draft a concise incident report for this production outage.

SEVERITY: {severity}
TICKET: {ticket_key}
AFFECTED SERVICES: {', '.join(affected_services)}
TIMELINE: {timeline}

ROOT CAUSE:
{root_cause}

REMEDIATION TAKEN:
{fix}

Format the report with these sections:
## Incident Summary
## Impact
## Timeline
## Root Cause Analysis
## Resolution Steps
## Action Items (to prevent recurrence)

Keep it under 400 words. Professional tone. No fluff.
"""
        return self.generate(prompt, system, max_tokens=600)


# Singleton
ollama_client = OllamaClient()


if __name__ == "__main__":
    print("🤖 Testing Ollama client...\n")
    resp = ollama_client.classify_severity(
        "Multiple FATAL errors in payment-service, connection pool exhausted",
        error_rate=0.45,
        affected_services=["payment-service", "api-gateway"],
    )
    print("Severity:", resp)

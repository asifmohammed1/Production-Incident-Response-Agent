"""
dashboard/index.html

Standalone HTML dashboard for the Incident Response Agent.
No build step needed — open in browser while API runs on :8000.
Uses SSE for live log streaming and polls API for incident updates.
"""

HTML_CONTENT = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Incident Response Agent</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Syne:wght@400;600;800&display=swap');

  :root {
    --bg:       #090b10;
    --surface:  #0d1117;
    --border:   #1c2333;
    --accent:   #f97316;
    --green:    #22c55e;
    --red:      #ef4444;
    --yellow:   #eab308;
    --blue:     #3b82f6;
    --muted:    #6b7280;
    --text:     #e2e8f0;
    --dim:      #94a3b8;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* Grid noise overlay */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      linear-gradient(rgba(249,115,22,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(249,115,22,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
  }

  .container { position: relative; z-index: 1; max-width: 1400px; margin: 0 auto; padding: 24px; }

  /* Header */
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 0 32px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 32px;
  }

  .logo {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .logo-icon {
    width: 42px; height: 42px;
    background: var(--accent);
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 20px;
  }

  .logo-text h1 {
    font-family: 'Syne', sans-serif;
    font-size: 20px;
    font-weight: 800;
    color: #fff;
    letter-spacing: -0.5px;
  }

  .logo-text p {
    font-size: 11px;
    color: var(--muted);
    letter-spacing: 2px;
    text-transform: uppercase;
  }

  .status-pill {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 16px;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 12px;
    color: var(--dim);
  }

  .pulse {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
  }

  .pulse.red { background: var(--red); }

  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.4; transform: scale(0.8); }
  }

  /* Stats bar */
  .stats-bar {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 28px;
  }

  .stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    position: relative;
    overflow: hidden;
  }

  .stat-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
  }

  .stat-card.orange::before { background: var(--accent); }
  .stat-card.red::before    { background: var(--red); }
  .stat-card.green::before  { background: var(--green); }
  .stat-card.blue::before   { background: var(--blue); }

  .stat-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--muted);
    margin-bottom: 10px;
  }

  .stat-value {
    font-family: 'Syne', sans-serif;
    font-size: 32px;
    font-weight: 800;
    color: #fff;
    line-height: 1;
  }

  .stat-sub {
    font-size: 11px;
    color: var(--dim);
    margin-top: 6px;
  }

  /* Main grid */
  .main-grid {
    display: grid;
    grid-template-columns: 1fr 420px;
    gap: 20px;
  }

  .panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }

  .panel-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .panel-title {
    font-family: 'Syne', sans-serif;
    font-size: 13px;
    font-weight: 600;
    color: #fff;
    letter-spacing: 0.5px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .badge {
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 999px;
    font-family: 'JetBrains Mono', monospace;
  }

  .badge.live { background: rgba(34,197,94,0.15); color: var(--green); border: 1px solid rgba(34,197,94,0.3); }
  .badge.count { background: rgba(249,115,22,0.15); color: var(--accent); border: 1px solid rgba(249,115,22,0.3); }

  /* Log viewer */
  .log-viewer {
    height: 380px;
    overflow-y: auto;
    padding: 16px;
    font-size: 11px;
    line-height: 1.7;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }

  .log-line {
    display: flex;
    gap: 10px;
    padding: 2px 0;
    border-radius: 4px;
    animation: fadeIn 0.3s ease;
  }

  @keyframes fadeIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; } }

  .log-ts { color: var(--muted); min-width: 140px; flex-shrink: 0; }
  .log-level { min-width: 60px; flex-shrink: 0; font-weight: 600; }
  .log-service { color: var(--blue); min-width: 140px; flex-shrink: 0; }
  .log-msg { color: var(--text); word-break: break-all; }

  .level-INFO  { color: var(--dim); }
  .level-DEBUG { color: #64748b; }
  .level-WARN  { color: var(--yellow); }
  .level-ERROR { color: var(--red); }
  .level-FATAL { color: var(--red); text-shadow: 0 0 8px rgba(239,68,68,0.5); }

  /* Analyze controls */
  .analyze-bar {
    padding: 16px 20px;
    border-top: 1px solid var(--border);
    display: flex;
    gap: 10px;
    align-items: center;
  }

  .input-field {
    flex: 1;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: var(--text);
    outline: none;
    transition: border-color 0.2s;
  }

  .input-field:focus { border-color: var(--accent); }

  .btn {
    padding: 10px 20px;
    border: none;
    border-radius: 8px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
  }

  .btn-primary {
    background: var(--accent);
    color: #000;
  }
  .btn-primary:hover { background: #fb923c; transform: translateY(-1px); }
  .btn-primary:disabled { background: var(--muted); cursor: not-allowed; transform: none; }

  .btn-ghost {
    background: transparent;
    color: var(--dim);
    border: 1px solid var(--border);
  }
  .btn-ghost:hover { border-color: var(--accent); color: var(--accent); }

  /* Incident list */
  .incident-list {
    height: 460px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }

  .incident-item {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background 0.15s;
    animation: fadeIn 0.3s ease;
  }

  .incident-item:hover { background: rgba(249,115,22,0.05); }
  .incident-item.selected { background: rgba(249,115,22,0.08); border-left: 2px solid var(--accent); }

  .inc-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
  }

  .inc-id {
    font-size: 12px;
    font-weight: 600;
    color: var(--accent);
  }

  .sev-badge {
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
    text-transform: uppercase;
  }

  .sev-Critical { background: rgba(239,68,68,0.2); color: var(--red); }
  .sev-High     { background: rgba(249,115,22,0.2); color: var(--accent); }
  .sev-Medium   { background: rgba(234,179,8,0.2); color: var(--yellow); }
  .sev-Low      { background: rgba(34,197,94,0.2); color: var(--green); }

  .inc-services {
    font-size: 11px;
    color: var(--blue);
    margin-bottom: 4px;
  }

  .inc-time {
    font-size: 10px;
    color: var(--muted);
  }

  /* Detail panel */
  .detail-panel {
    margin-top: 20px;
    grid-column: 1 / -1;
  }

  .detail-content {
    padding: 24px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
  }

  .detail-section h3 {
    font-family: 'Syne', sans-serif;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--accent);
    margin-bottom: 12px;
  }

  .detail-section p, .detail-section pre {
    font-size: 12px;
    line-height: 1.7;
    color: var(--dim);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 200px;
    overflow-y: auto;
  }

  .empty-state {
    padding: 60px 20px;
    text-align: center;
    color: var(--muted);
    font-size: 12px;
  }

  .empty-state .icon { font-size: 40px; margin-bottom: 16px; }

  /* Loading */
  .loading {
    display: inline-flex;
    gap: 4px;
    align-items: center;
  }

  .loading span {
    width: 4px; height: 4px;
    border-radius: 50%;
    background: var(--accent);
    animation: bounce 1s infinite;
  }

  .loading span:nth-child(2) { animation-delay: 0.15s; }
  .loading span:nth-child(3) { animation-delay: 0.30s; }

  @keyframes bounce {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-6px); }
  }

  /* Toasts */
  #toasts {
    position: fixed;
    bottom: 24px; right: 24px;
    display: flex; flex-direction: column; gap: 8px;
    z-index: 100;
  }

  .toast {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 18px;
    font-size: 12px;
    min-width: 280px;
    animation: slideUp 0.3s ease;
    border-left: 3px solid var(--accent);
  }

  .toast.success { border-left-color: var(--green); }
  .toast.error   { border-left-color: var(--red); }

  @keyframes slideUp { from { transform: translateY(20px); opacity: 0; } }

  @media (max-width: 900px) {
    .main-grid { grid-template-columns: 1fr; }
    .stats-bar { grid-template-columns: repeat(2, 1fr); }
    .detail-content { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<div id="toasts"></div>

<div class="container">
  <header>
    <div class="logo">
      <div class="logo-icon">🚨</div>
      <div class="logo-text">
        <h1>Incident Response Agent</h1>
        <p>Auto-Pilot for Production Outages</p>
      </div>
    </div>
    <div class="status-pill">
      <div class="pulse" id="api-pulse"></div>
      <span id="api-status">Connecting...</span>
    </div>
  </header>

  <!-- Stats Bar -->
  <div class="stats-bar">
    <div class="stat-card orange">
      <div class="stat-label">Total Analyzed</div>
      <div class="stat-value" id="stat-total">0</div>
      <div class="stat-sub">log files processed</div>
    </div>
    <div class="stat-card red">
      <div class="stat-label">Anomalies Detected</div>
      <div class="stat-value" id="stat-anomalies">0</div>
      <div class="stat-sub">incidents triggered</div>
    </div>
    <div class="stat-card green">
      <div class="stat-label">Tickets Created</div>
      <div class="stat-value" id="stat-tickets">0</div>
      <div class="stat-sub">via Jira MCP tool</div>
    </div>
    <div class="stat-card blue">
      <div class="stat-label">Avg Error Rate</div>
      <div class="stat-value" id="stat-errrate">0%</div>
      <div class="stat-sub">across all incidents</div>
    </div>
  </div>

  <!-- Main Grid -->
  <div class="main-grid">

    <!-- Left: Live Logs -->
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">
          📡 Live Log Stream
          <span class="badge live">LIVE</span>
        </div>
        <button class="btn btn-ghost" onclick="clearLogs()">Clear</button>
      </div>

      <div class="log-viewer" id="log-viewer">
        <div class="empty-state">
          <div class="icon">📋</div>
          <div>Waiting for log stream...</div>
          <div style="margin-top:8px;color:#374151;font-size:10px;">
            Run <code>datasets/generate_sample_logs.py</code> to generate test data
          </div>
        </div>
      </div>

      <div class="analyze-bar">
        <input
          class="input-field"
          id="log-path-input"
          placeholder="Log file path (leave empty for default)"
          value=""
        />
        <button class="btn btn-primary" id="analyze-btn" onclick="analyzeLog()">
          ⚡ Analyze
        </button>
        <button class="btn btn-ghost" onclick="generateSampleData()">
          🎲 Sample
        </button>
      </div>
    </div>

    <!-- Right: Incidents -->
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">
          🔴 Incidents
          <span class="badge count" id="incident-count">0</span>
        </div>
        <button class="btn btn-ghost" onclick="loadIncidents()">↻ Refresh</button>
      </div>

      <div class="incident-list" id="incident-list">
        <div class="empty-state">
          <div class="icon">🟢</div>
          <div>No incidents yet</div>
          <div style="margin-top:8px;color:#374151;font-size:10px;">Click Analyze to start</div>
        </div>
      </div>
    </div>

  </div>

  <!-- Detail Panel -->
  <div id="detail-panel" style="display:none;" class="panel detail-panel">
    <div class="panel-header">
      <div class="panel-title">🧠 Incident Analysis — <span id="detail-id"></span></div>
      <button class="btn btn-ghost" onclick="closeDetail()">✕ Close</button>
    </div>
    <div class="detail-content" id="detail-content"></div>
  </div>

</div>

<script>
const API = 'http://localhost:8000';
let selectedIncidentId = null;
let incidents = [];
let analyzing = false;
let logCount = 0;

// ── API Health ─────────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const r = await fetch(`${API}/api/health`);
    if (r.ok) {
      document.getElementById('api-status').textContent = 'API Connected';
      document.getElementById('api-pulse').classList.remove('red');
    } else {
      throw new Error();
    }
  } catch {
    document.getElementById('api-status').textContent = 'API Offline';
    document.getElementById('api-pulse').classList.add('red');
  }
}

// ── Log Level Color ────────────────────────────────────────────────────────
function levelClass(level) {
  return `level-${level || 'INFO'}`;
}

// ── Parse log line ─────────────────────────────────────────────────────────
function parseLogLine(line) {
  const m = line.match(/\[(.+?)\] \[(\w+)\] \[([\w-]+)\] \[[\w-]+\] (.+)/);
  if (!m) return { ts: '', level: 'INFO', service: '', msg: line };
  return { ts: m[1], level: m[2], service: m[3], msg: m[4] };
}

// ── Render log line ────────────────────────────────────────────────────────
function renderLogLine(rawLine) {
  const { ts, level, service, msg } = parseLogLine(rawLine);
  const div = document.createElement('div');
  div.className = 'log-line';
  div.innerHTML = `
    <span class="log-ts">${ts}</span>
    <span class="log-level ${levelClass(level)}">${level}</span>
    <span class="log-service">${service}</span>
    <span class="log-msg">${msg.substring(0, 120)}</span>
  `;
  return div;
}

// ── Live log stream (SSE) ──────────────────────────────────────────────────
function startLogStream() {
  const viewer = document.getElementById('log-viewer');
  viewer.innerHTML = '';

  const es = new EventSource(`${API}/api/stream/logs`);

  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.error) return;
    if (!data.line) return;

    if (logCount === 0) viewer.innerHTML = '';
    logCount++;

    const el = renderLogLine(data.line);
    viewer.appendChild(el);

    // Auto-scroll
    if (viewer.scrollTop + viewer.clientHeight > viewer.scrollHeight - 100) {
      viewer.scrollTop = viewer.scrollHeight;
    }

    // Keep max 500 lines
    while (viewer.children.length > 500) {
      viewer.removeChild(viewer.firstChild);
    }
  };

  es.onerror = () => {
    // SSE will auto-reconnect; this is normal when API is offline
  };
}

// ── Analyze ────────────────────────────────────────────────────────────────
async function analyzeLog() {
  if (analyzing) return;
  analyzing = true;

  const btn  = document.getElementById('analyze-btn');
  const path = document.getElementById('log-path-input').value.trim();

  btn.innerHTML = '<span class="loading"><span></span><span></span><span></span></span>';
  btn.disabled  = true;

  try {
    const body = path ? { log_path: path } : {};
    const r    = await fetch(`${API}/api/analyze/sync`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });

    if (!r.ok) {
      const err = await r.json();
      toast(err.detail || 'Analysis failed', 'error');
      return;
    }

    const result = await r.json();
    incidents.unshift(result);
    renderIncidentList();
    updateStats();

    if (result.anomaly_detected) {
      toast(`🚨 Incident detected! Severity: ${result.severity?.split(' ')[0] || 'Unknown'}`, 'error');
    } else {
      toast('✅ Analysis complete — no anomalies detected', 'success');
    }
  } catch (e) {
    toast('Could not reach API — is the server running?', 'error');
  } finally {
    btn.textContent = '⚡ Analyze';
    btn.disabled    = false;
    analyzing       = false;
  }
}

// ── Generate sample data (calls API to use existing sample files) ──────────
async function generateSampleData() {
  // Just point to the pre-generated incident log
  document.getElementById('log-path-input').value = 'datasets/sample_logs/incident.log';
  toast('📂 Pointed to sample incident log — click Analyze', 'success');
}

// ── Load incidents ─────────────────────────────────────────────────────────
async function loadIncidents() {
  try {
    const r    = await fetch(`${API}/api/incidents?limit=20`);
    const data = await r.json();
    incidents  = data.incidents || [];
    renderIncidentList();
    updateStats();
  } catch {}
}

// ── Render incident list ───────────────────────────────────────────────────
function renderIncidentList() {
  const list = document.getElementById('incident-list');
  document.getElementById('incident-count').textContent = incidents.length;

  if (!incidents.length) {
    list.innerHTML = '<div class="empty-state"><div class="icon">🟢</div><div>No incidents yet</div></div>';
    return;
  }

  list.innerHTML = incidents.map(inc => {
    const sev = (inc.severity || 'Unknown').split(' ')[0];
    const services = (inc.affected_services || []).slice(0, 2).join(', ') || '—';
    const selected = inc.incident_id === selectedIncidentId ? 'selected' : '';
    return `
      <div class="incident-item ${selected}" onclick="showDetail('${inc.incident_id}')">
        <div class="inc-header">
          <span class="inc-id">${inc.incident_id}</span>
          ${inc.anomaly_detected
            ? `<span class="sev-badge sev-${sev}">${sev}</span>`
            : `<span class="sev-badge" style="background:rgba(34,197,94,0.1);color:#22c55e">Clean</span>`
          }
        </div>
        <div class="inc-services">${services}</div>
        <div class="inc-time">${inc.triggered_at || inc.completed_at || '—'}</div>
      </div>
    `;
  }).join('');
}

// ── Show incident detail ───────────────────────────────────────────────────
function showDetail(incidentId) {
  selectedIncidentId = incidentId;
  const inc = incidents.find(i => i.incident_id === incidentId);
  if (!inc) return;

  renderIncidentList();

  const panel   = document.getElementById('detail-panel');
  const content = document.getElementById('detail-content');
  document.getElementById('detail-id').textContent = incidentId;

  const sev      = (inc.severity || 'N/A').split(' ')[0];
  const errRate  = inc.error_rate ? (inc.error_rate * 100).toFixed(1) + '%' : 'N/A';
  const services = (inc.affected_services || []).join(', ') || 'None detected';

  content.innerHTML = `
    <div class="detail-section">
      <h3>🔬 Anomaly Summary</h3>
      <pre>${inc.anomaly_summary || 'No anomaly detected'}</pre>
    </div>
    <div class="detail-section">
      <h3>🧠 Root Cause</h3>
      <pre>${inc.root_cause || 'N/A'}</pre>
    </div>
    <div class="detail-section">
      <h3>🛠 Fix Suggestion</h3>
      <pre>${inc.fix_suggestion || 'N/A'}</pre>
    </div>
    <div class="detail-section">
      <h3>📋 Incident Report</h3>
      <pre>${inc.incident_report || 'N/A'}</pre>
    </div>
    <div class="detail-section">
      <h3>📊 Metadata</h3>
      <pre>Severity:  ${sev}
Error Rate: ${errRate}
Services:  ${services}
Ticket:    ${inc.ticket_key || 'N/A'}
Slack:     ${inc.slack_status || 'N/A'}
Completed: ${inc.completed_at || 'N/A'}</pre>
    </div>
    <div class="detail-section">
      <h3>🔄 Agent Execution Log</h3>
      <pre>${(inc.agent_log || []).join('\n') || 'N/A'}</pre>
    </div>
  `;

  panel.style.display = 'block';
  panel.scrollIntoView({ behavior: 'smooth' });
}

function closeDetail() {
  document.getElementById('detail-panel').style.display = 'none';
  selectedIncidentId = null;
  renderIncidentList();
}

// ── Update stats ───────────────────────────────────────────────────────────
function updateStats() {
  const total     = incidents.length;
  const anomalies = incidents.filter(i => i.anomaly_detected).length;
  const tickets   = incidents.filter(i => i.ticket_key && i.ticket_key !== 'INC-???').length;
  const avgErr    = total > 0
    ? (incidents.reduce((s, i) => s + (i.error_rate || 0), 0) / total * 100).toFixed(1)
    : 0;

  document.getElementById('stat-total').textContent     = total;
  document.getElementById('stat-anomalies').textContent = anomalies;
  document.getElementById('stat-tickets').textContent   = tickets;
  document.getElementById('stat-errrate').textContent   = `${avgErr}%`;
}

// ── Clear logs ─────────────────────────────────────────────────────────────
function clearLogs() {
  document.getElementById('log-viewer').innerHTML =
    '<div class="empty-state"><div class="icon">📋</div><div>Log cleared</div></div>';
  logCount = 0;
}

// ── Toast ──────────────────────────────────────────────────────────────────
function toast(msg, type = '') {
  const container = document.getElementById('toasts');
  const el        = document.createElement('div');
  el.className    = `toast ${type}`;
  el.textContent  = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

// ── Init ───────────────────────────────────────────────────────────────────
checkHealth();
setInterval(checkHealth, 10000);
startLogStream();
loadIncidents();
setInterval(loadIncidents, 15000);
</script>
</body>
</html>'''

if __name__ == "__main__":
    with open("index.html", "w") as f:
        f.write(HTML_CONTENT)
    print("✅ Dashboard written to dashboard/index.html")
    print("   Open in browser while API runs on http://localhost:8000")

"""
datasets/generate_sample_logs.py
Generates realistic HDFS/application logs for testing the pipeline.
Includes normal logs + injected anomalies (errors, outages, spikes).
"""
import random
import os
from datetime import datetime, timedelta

LOG_DIR = os.path.join(os.path.dirname(__file__), "sample_logs")
os.makedirs(LOG_DIR, exist_ok=True)

SERVICES = ["auth-service", "payment-service", "api-gateway", "db-connector", "notification-service"]
LEVELS   = ["INFO", "DEBUG", "WARN", "ERROR", "FATAL"]
NORMAL_WEIGHT   = [0.50, 0.25, 0.15, 0.08, 0.02]
ANOMALY_WEIGHT  = [0.10, 0.05, 0.10, 0.45, 0.30]

NORMAL_MESSAGES = [
    "Request processed successfully in {ms}ms",
    "User {uid} authenticated",
    "Cache hit for key {key}",
    "DB query executed in {ms}ms",
    "Heartbeat OK",
    "Connection pool size: {n}",
    "Scheduled job completed",
    "Response sent with status 200",
]

ANOMALY_MESSAGES = [
    "FATAL: Out of memory — heap space exhausted",
    "ERROR: Connection refused to database host {host}",
    "ERROR: Timeout after {ms}ms waiting for upstream",
    "FATAL: Disk I/O error on /var/data",
    "ERROR: NullPointerException in PaymentProcessor.java:142",
    "ERROR: Circuit breaker OPEN for auth-service",
    "FATAL: Thread pool exhausted — rejecting requests",
    "ERROR: SSL handshake failed with peer {host}",
    "ERROR: Response status 500 from downstream",
    "FATAL: Unhandled exception — service shutting down",
]

def random_message(messages):
    msg = random.choice(messages)
    return msg.format(
        ms=random.randint(10, 9999),
        uid=f"user_{random.randint(1000, 9999)}",
        key=f"cache:{random.randint(1,100)}",
        host=f"10.0.{random.randint(0,255)}.{random.randint(0,255)}",
        n=random.randint(1, 50),
    )

def generate_log_line(timestamp: datetime, anomaly: bool = False) -> str:
    service = random.choice(SERVICES)
    level   = random.choices(
        LEVELS,
        weights=ANOMALY_WEIGHT if anomaly else NORMAL_WEIGHT
    )[0]
    msg = random_message(ANOMALY_MESSAGES if anomaly else NORMAL_MESSAGES)
    thread = f"thread-{random.randint(1, 20)}"
    return f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] [{level}] [{service}] [{thread}] {msg}"

def generate_normal_log(filename="normal.log", lines=500):
    path = os.path.join(LOG_DIR, filename)
    start = datetime.now() - timedelta(hours=2)
    with open(path, "w") as f:
        for i in range(lines):
            ts = start + timedelta(seconds=i * 10)
            f.write(generate_log_line(ts, anomaly=False) + "\n")
    print(f"✅ Generated normal log → {path}")

def generate_incident_log(filename="incident.log", lines=500, incident_start=400):
    """Normal logs + sudden anomaly spike from line incident_start onwards."""
    path = os.path.join(LOG_DIR, filename)
    start = datetime.now() - timedelta(hours=1)
    with open(path, "w") as f:
        for i in range(lines):
            ts = start + timedelta(seconds=i * 5)
            anomaly = i >= incident_start
            f.write(generate_log_line(ts, anomaly=anomaly) + "\n")
    print(f"✅ Generated incident log → {path}")
    print(f"   ⚡ Anomaly starts at line {incident_start}")

def generate_streaming_log(filename="stream.log"):
    """Continuously appended log for live monitoring simulation."""
    path = os.path.join(LOG_DIR, filename)
    open(path, "w").close()  # clear
    print(f"✅ Streaming log ready → {path} (append to this file to simulate live logs)")
    return path

if __name__ == "__main__":
    generate_normal_log()
    generate_incident_log()
    generate_streaming_log()
    print("\n📁 All sample datasets ready in:", LOG_DIR)

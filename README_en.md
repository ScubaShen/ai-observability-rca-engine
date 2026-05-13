# 🚨 AI Observability RCA Platform

[![繁體中文](https://img.shields.io/badge/README-%E7%B9%81%E9%AB%94%E4%B8%AD%E6%96%87-green)](README.md)

AI Observability RCA Platform is an incident analysis and root cause analysis (RCA) system designed for distributed systems. It transforms Logs, Metrics, and Traces into explainable, verifiable, and traceable RCA results, and supports on-call investigation through an Operator Console and AI Copilot.

---

## 📌 System Positioning

This system sits between Observability Telemetry and Operator Workflow. It converts raw observability data into:

- Incident Candidate
- Evidence Timeline
- Root Cause Hypothesis
- RCA Result
- Operator Report
- RAG / Copilot Context

Core philosophy:

```text
Evidence → Reasoning → Conclusion
```

---

## 🧠 Core Features

### 1. Evidence-first RCA

All conclusions must be grounded in traceable evidence. The system does not allow the LLM to invent unsupported explanations.

### 2. Deterministic RCA Engine

The core RCA pipeline does not depend on an LLM. This makes the system testable, replayable, and debuggable.

### 3. Explainable Evidence Scoring

Evidence score is not a probability. It is an investigation ranking signal for on-call operators. Each score can be broken down by factors such as signal type, severity, correlation, trace coherence, and cross-signal agreement.

### 4. Hybrid RAG

This is not a pure vector-search RAG system. It combines exact lookup, keyword search, vector retrieval, historical incident recall, and graph context retrieval.

### 5. Full Fallback Architecture

When the LLM, PostgreSQL, or Neo4j is unavailable, the system can still preserve minimum operational capability through the deterministic path and JSONL artifact store.

### 6. Operator-first Console

The Console uses incidents as the primary entry point instead of a chat-first experience. This prevents users from trusting AI-generated answers before reviewing the underlying evidence.

---

## 🏗️ Technical Architecture

```text
┌───────────────────────────────────────────────┐
│              Microservices / Apps             │
│  Java Backend / APIs / Distributed Services   │
└───────────────────────────────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│        Observability Collection Layer         │
│  OpenTelemetry SDK / Grafana Alloy / FluentBit│
└───────────────────────────────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│                    Kafka                      │
│  observability.logs | metrics | traces        │
└───────────────────────────────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│                RCA Engine Worker              │
│  ┌─────────────────────────────────────────┐  │
│  │ Normalize: JSON / OTLP → NormalizedEvent│  │
│  └─────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────┐  │
│  │ Signal Extraction                       │  │
│  │ log.error / metric.anomaly / trace.*    │  │
│  └─────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────┐  │
│  │ Incident Correlation                    │  │
│  │ service + env + window + trace_id       │  │
│  └─────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────┐  │
│  │ Deterministic RCA Pipeline              │  │
│  │ Timeline → Evidence → Causal → Ranking  │  │
│  └─────────────────────────────────────────┘  │
└───────────────────────────────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│                Storage Layer                  │
│  PostgreSQL  │  JSONL Fallback  │  Neo4j      │
└───────────────────────────────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│              RAG / Copilot Layer              │
│  Retrieval → Rerank → LLM(optional) → Verify  │
│  Exact + Keyword + Vector + Graph + History   │
└───────────────────────────────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│              API / Console / Copilot          │
│  FastAPI / Streamlit Console / AI Assistant   │
└───────────────────────────────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│               Operator Workflow               │
│  Incident → Evidence → Graph → Copilot        │
└───────────────────────────────────────────────┘
```

---

## 🔄 Data Flow

```text
Kafka raw telemetry
  → normalize into shared event model
  → extract high-value operational signals
  → group signals into incident candidates
  → load incident-scoped context
  → score evidence
  → build timeline and causal links
  → generate root-cause hypotheses
  → rank hypotheses
  → persist RCA result and agent report
  → index artifacts for RAG
  → answer operator questions with citations
```

---

## 📂 Project Structure

```text
src/rca_engine/
  workers/       Kafka intake and main processing pipeline
  processors/    High-value event extraction for logs / metrics / traces
  rca/           Deterministic RCA pipeline
  storage/       JSONL / PostgreSQL / Neo4j storage abstraction
  routers/       FastAPI router modules
  rag/           Hybrid retrieval, rerank, verification, LLM provider
  evaluation/    Offline eval runner, metrics, fixtures-backed baseline
  agents/        Operator-facing reports and runbook recommendation
  console/       Streamlit RCA Console
  models/        Shared data models
```

---

## 🚀 Quick Start

```bash
docker compose up -d
```

Health check:

```bash
curl -sS http://localhost:18000/health
curl -sS http://localhost:18000/storage/health
```

Copilot:

```bash
curl -sS -X POST http://localhost:18000/copilot/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is the most likely root cause?","limit":5,"mode":"auto"}'
```

Open the Streamlit RCA Console: http://localhost:8501

---

## 📚 Documentation

- [docs/architecture.md](docs/architecture.md): system architecture and design tradeoffs
- [docs/rca-design.md](docs/rca-design.md): RCA pipeline, evidence scoring, and causal reasoning
- [docs/rag.md](docs/rag.md): Hybrid RAG, rerank, LLM, and verification
- [docs/evaluation.md](docs/evaluation.md): offline deterministic eval, Docker usage, metric glossary, and baseline acceptance criteria
- [docs/operator-console.md](docs/operator-console.md): on-call investigation entry point and Console workflow
- [docs/runbook.md](docs/runbook.md): startup, verification, troubleshooting, and reindex
- [docs/security.md](docs/security.md): secret handling, LLM boundary, and automation restrictions

---

## 🧩 System Boundary

### Included

- Incident analysis
- Root cause reasoning
- Evidence aggregation
- RCA reporting
- AI-assisted investigation

### Not Included

- Automatic rollback / restart / scale
- Ticket executor
- Approval workflow
- Full workflow orchestration platform
- Replacement for monitoring systems

---

## 🧭 Summary

This is not a system that lets AI guess the root cause. It builds an explainable incident analysis pipeline:

```text
Telemetry → Evidence → Incident → RCA → Retrieval → Copilot → Operator Decision
```

The LLM improves explanation quality, but it is not the core decision maker of the RCA system.

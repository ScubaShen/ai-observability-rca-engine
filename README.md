# 🚨 AI Observability RCA 平台

[![English](https://img.shields.io/badge/README-English-blue)](README_en.md)

AI Observability RCA 平台是一個面向分散式系統的故障分析與根因分析系統，將 Logs、Metrics、Traces 轉換為可解釋、可驗證、可追溯的 RCA 結果，並透過 Console 與 Copilot 輔助值班排查。

---

## 📌 系統定位

本系統位於 Observability Telemetry 與 Operator Workflow 之間，負責將原始觀測資料轉換為：

- Incident Candidate
- Evidence Timeline
- Root Cause Hypothesis
- RCA Result
- Operator Report
- RAG / Copilot Context

核心理念：

```text
Evidence → Reasoning → Conclusion
```

---

## 🧠 核心特性

### 1. Evidence-first RCA

所有結論必須來自可追溯證據，不讓 LLM 憑空推論。

### 2. Deterministic RCA Engine

RCA 核心流程不依賴 LLM，確保可測試、可重放、可 debug。

### 3. Explainable Evidence Scoring

Evidence score 不是機率，而是值班排查排序訊號。每個分數都可拆解為 signal type、severity、correlation、trace coherence、cross-signal agreement 等因素。

### 4. Hybrid RAG

不是單純向量檢索，而是結合 exact、keyword、vector、historical incident、graph context 的多路召回。

### 5. Full Fallback Architecture

LLM、PostgreSQL 或 Neo4j 不可用時，系統仍可透過 deterministic path 與 JSONL artifact store 保留最低可操作能力。

### 6. Operator-first Console

Console 以 Incident 為入口，而不是 Chat-first，避免使用者未檢查 evidence 就直接相信 AI 回答。

---

## 🏗️ 技術架構

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

## 🔄 資料流

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

## 📂 專案結構

```text
src/rca_engine/
  workers/       Kafka intake 與主處理鏈路
  processors/    logs / metrics / traces 高價值事件抽取
  rca/           deterministic RCA pipeline
  storage/       JSONL / PostgreSQL / Neo4j 儲存抽象
  routers/       FastAPI router 分層
  rag/           hybrid retrieval、rerank、verification、LLM provider
  evaluation/    offline eval runner、metrics、fixtures-backed baseline
  agents/        operator-facing report 與 runbook recommendation
  console/       Streamlit RCA Console
  models/        共享資料模型
```

---

## 🚀 快速啟動

```bash
docker compose up -d
```

健康檢查：

```bash
curl -sS http://localhost:18000/health
curl -sS http://localhost:18000/storage/health
```

查詢事件與 incident：

```bash
curl -sS 'http://localhost:18000/events/search?service=checkout&limit=50'
curl -sS 'http://localhost:18000/incidents/search?service=checkout&limit=50'
```

Copilot：

```bash
curl -sS -X POST http://localhost:18000/copilot/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is the most likely root cause?","limit":5,"mode":"auto"}'
```

開啟 Streamlit RCA Console：http://localhost:8501

---

## 📚 文件導覽

- [docs/architecture.md](docs/architecture.md)：系統架構與設計取捨
- [docs/rca-design.md](docs/rca-design.md)：RCA pipeline、evidence scoring、causal reasoning
- [docs/rag.md](docs/rag.md)：Hybrid RAG、rerank、LLM、verification
- [docs/evaluation.md](docs/evaluation.md)：offline deterministic eval、Docker 操作、指標縮寫與 baseline 驗收標準
- [docs/operator-console.md](docs/operator-console.md)：值班排查入口與 Console 工作流
- [docs/runbook.md](docs/runbook.md)：啟動、驗證、排查與 reindex
- [docs/security.md](docs/security.md)：Secret、LLM 邊界與自動化限制

---

## 🧩 系統邊界

### 包含

- 故障分析
- 根因推理
- 證據聚合
- RCA 報告
- AI 輔助排查

### 不包含

- 自動 rollback / restart / scale
- ticket executor
- approval workflow
- 完整工作流編排平台
- 監控系統替代品

---

## 🧭 總結

這不是「讓 AI 猜根因」的系統，而是建立一條可解釋的故障分析鏈路：

```text
Telemetry → Evidence → Incident → RCA → Retrieval → Copilot → Operator Decision
```

LLM 是提升說明能力的工具，不是 RCA 的核心決策者。

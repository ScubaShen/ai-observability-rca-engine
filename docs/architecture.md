# 🏗️ 系統架構設計

## 目標

本文件說明 AI Observability RCA 平台的整體架構、資料流、核心組件與主要設計取捨。

這份文件回答三個問題：

1. 系統如何從 telemetry 產生 RCA 結果？
2. 為什麼採用 deterministic-first 架構？
3. 各層責任邊界如何劃分？

---

## 系統資料流

```text
Observability Telemetry
  → Normalization
  → High-value Signal Extraction
  → Incident Correlation
  → Deterministic RCA
  → Storage
  → RAG Indexing
  → API / Console / Copilot
```

每一層都保留 artifact，原因是 RCA 系統必須能回答：

> 為什麼得出這個判斷？

而不是只輸出一段看似合理的文字。

---

## 核心組件

### 1. Normalization

將 JSON / OTLP logs / metrics / traces 轉換為統一事件模型 `NormalizedEvent`。

目的：

- 降低下游對來源格式的耦合
- 統一事件欄位，例如 service、env、severity、trace_id
- 讓 RCA、storage、retrieval 使用同一套事件語義

---

### 2. High-value Signal Extraction

原始 logs / metrics / traces 不直接進入 RCA。

系統先抽取高價值訊號：

```text
log.error_pattern
metric.anomaly
trace.error
trace.slow_span
```

設計原因：

- raw telemetry 噪音高
- RCA 需要的是可行動訊號
- 訊號抽取可降低後續推理成本

---

### 3. Incident Correlation

Incident correlation 負責決定哪些訊號屬於同一個 incident candidate。

目前分群依據：

```text
service + env + time_window + trace_id
```

這裡不判斷 root cause，只處理事件分群。這樣可以避免「分群規則」和「根因推理」混在一起。

---

### 4. Deterministic RCA Engine

RCA 核心流程：

```text
Context Loader
  → Timeline Builder
  → Evidence Scoring
  → Dependency Analyzer
  → Causal Graph Builder
  → Hypothesis Generator
  → Root Cause Ranker
```

設計目標：

- 可解釋
- 可測試
- 可重放
- 不依賴 LLM

---

### 5. Storage Layer

| 儲存         | 角色                                                  |
| ---------- | --------------------------------------------------- |
| PostgreSQL | 主查詢儲存，承接 events、incidents、RCA results、RAG documents |
| JSONL      | fallback、debug、replay、本地 artifact                   |
| Neo4j      | incident graph 與 causal relationship projection     |

PostgreSQL / Neo4j 不可用時，系統仍可透過 JSONL 保留最低可操作能力。

---

### 6. RAG / Copilot Layer

RAG 不是直接檢索 raw logs，而是檢索 RCA artifact：

- RCA result
- evidence summary
- agent report
- runbook
- historical incident
- graph context

這樣可以降低 raw telemetry 噪音，讓 Copilot 回答更接近 operator 排查語境。

---

## 主要設計取捨

| 決策                         | 好處                 | 代價                           |
| -------------------------- | ------------------ | ---------------------------- |
| 單 worker 串完整分析鏈            | 容易 debug、容易 replay | 吞吐量不如多 stage pipeline        |
| deterministic RCA          | 可解釋、可測試、無 LLM 也能跑  | 規則需要持續維護                     |
| evidence heuristic scoring | 分數可拆解              | 不是統計校準機率                     |
| artifact-first RAG         | 降低噪音、提升可用性         | artifact 品質會影響召回             |
| JSONL fallback             | 本地可操作、debug 方便     | 不是 multi-primary replication |
| Neo4j 作 projection         | 圖查詢不影響主流程          | 需維護額外 projection             |

---

## 為什麼不讓 LLM 成為 RCA 核心

RCA 是 production-critical workflow，需要：

- 可重現
- 可驗證
- 可測試
- 可回放
- 可降級

LLM 適合做總結與說明，不適合作為核心評分與決策引擎。

因此系統採用：

```text
Deterministic RCA first
Optional LLM synthesis second
```

---

## 系統邊界

本系統負責：

- 故障分析
- 根因推理
- 證據聚合
- RCA 報告
- AI 輔助排查

本系統不負責：

- 自動 rollback
- 自動 restart
- 自動 scale
- ticket executor
- 完整 orchestration platform

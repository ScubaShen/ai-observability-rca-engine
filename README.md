# AI Observability RCA Engine

[English Overview](README.en.md)

AI Observability RCA Engine 是一個面向容器環境的 incident analysis 與 deterministic RCA 引擎，用來把 logs、metrics、traces 等 observability telemetry，轉成可查詢的 incident candidate、RCA 結果、runbook 建議與 operator workflow 輸出。

它適合放在既有 observability stack 裡，承接 Kafka 中的原始 telemetry，完成標準化、關聯、推理、儲存與檢索，而不是自己充當完整 observability platform。

## 項目簡介

這個項目要解決的核心問題是：當系統已經有 logs、metrics、traces 與 Kafka 流水線時，如何把分散的訊號整理成「可被人和工具直接消費」的 incident 分析結果，而不是只停留在單點告警或孤立事件。

它目前提供的是一條偏工程實用、可容器化部署、可在無外部 LLM 的情況下運行的 RCA 主流程。

## 核心能力

- 接收 Kafka 中的 logs、metrics、traces 原始 telemetry，並轉成統一事件模型
- 從原始訊號中抽取 high-value events，例如 error pattern、metric anomaly、trace error
- 依據 service、env、trace、時間窗口等條件關聯成 incident candidate
- 透過 deterministic RCA pipeline 產生 timeline、evidence、hypothesis 與 ranking
- 輸出 operator report、runbook recommendation、postmortem draft 與 retrieval context
- 提供 RCA Console 與 API，支援查詢、檢索、reindex 與 feedback flow

## 適用場景

- 你已經有 Kafka 作為 observability telemetry 匯流排
- 你希望把分散的訊號整理成結構化 incident analysis 結果
- 你需要一個可驗證、可追蹤、可 fallback 的 RCA 引擎，而不是純 LLM 黑盒分析
- 你希望保留後續接入 LLM 的能力，但不讓系統基本功能依賴模型服務

## 系統流程

```text
Kafka raw telemetry
  -> normalization
  -> high-value event extraction
  -> incident correlation
  -> deterministic RCA orchestration
  -> operator report generation
  -> storage sync and retrieval indexing
  -> API / RCA Console consumers
```

## 目錄結構

```text
src/rca_engine/
  ├─ workers/      Kafka intake 與主處理鏈路
  ├─ processors/   logs / metrics / traces 高價值事件抽取
  ├─ rca/          deterministic RCA pipeline
  ├─ storage/      JSONL / PostgreSQL / Neo4j 儲存抽象
  ├─ rag/          retrieval、ranking、verification、optional LLM
  ├─ agents/       operator-facing report 與 runbook recommendation
  ├─ console/      Streamlit RCA Console
  └─ models/       共享資料模型

docs/              系統設計與運維文檔
infra/             初始化 schema 與基礎設施腳本
runtime/           本地開發或 demo 的運行時狀態與輸出
```

### 1. 建置映像

```bash
docker compose -f docker-compose-java-observability-platorm.yml build ai-observability-rca-engine
```

### 2. 啟動服務

```bash
docker compose -f docker-compose-java-observability-platorm.yml up \
  postgres neo4j ai-observability-rca-engine
```

### 3. 驗證健康狀態

```bash
curl -sS http://localhost:18000/health
curl -sS http://localhost:18000/storage/health
```

### 4. 驗證檢索與 RCA 問答

```bash
curl -sS 'http://localhost:18000/knowledge/search?q=application%20exception'

curl -sS -X POST http://localhost:18000/copilot/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"目前最可能的根因是什麼？","limit":5,"mode":"auto"}'
```

## 功能入口

核心查詢接口：

- `GET /health`
- `GET /storage/health`
- `GET /events/latest`
- `GET /incidents/candidates/latest`
- `GET /rca/latest`
- `GET /rca/{incident_id}`
- `GET /agents/reports/latest`
- `GET /agents/reports/{incident_id}`

檢索與 operator workflow 接口：

- `GET /knowledge/search`
- `POST /copilot/chat`
- `GET /copilot/sessions`
- `POST /copilot/feedback`
- `POST /rag/reindex`
- `GET /incidents/{incident_id}/postmortem-draft`

## 驗證方式

建議的最小驗證順序：

1. 在容器內執行單元測試
2. 在相同環境執行 `ruff check src tests`
3. 在相同環境執行 `mypy src`
4. 啟動服務後檢查 `/health`
5. 驗證 `/knowledge/search` 與 `/copilot/chat`

容器內測試示例：

```bash
docker compose -f docker-compose-java-observability-platorm.yml run --rm \
  --no-deps ai-observability-rca-engine pytest
```

## 事件模型與儲存

所有 high-value events 會使用 `NormalizedEvent` 統一封裝，模型定義位於 [src/rca_engine/models/](/Users/worker/programs/ai-observability-rca-engine/src/rca_engine/models/)。

預設輸出與儲存策略：

- `runtime/output`：永遠保留 JSONL 輸出，方便 debug 與 fallback read
- PostgreSQL：主結構化查詢與 retrieval document 儲存
- Neo4j：incident graph 與 causal relationship 投影

另外若存在：

- `runtime/postgres`
- `runtime/neo4j`

應將它們視為本地開發或 demo 環境中的 runtime state，而不是源碼包內容。

## 限制與非目標

- RCA 推理目前以 deterministic / heuristic 流程為主，不代表因果確定性
- LLM synthesis 是 optional，系統基本功能不應依賴外部模型服務
- 預設 embedding provider 為 deterministic 本地實作，重點在可運行與可替換，不在語義能力極致
- 本項目不是自動修復系統，不會執行 restart、rollback、approval workflow 或 ticket automation
- `runtime/` 下的本地資料屬於運行時狀態，不應視為正式結構化資產

## 文檔導航

- [英文版 README](README.en.md)
- [系統設計文檔](docs/architecture.md)
- [運行與維護文檔](docs/operations.md)

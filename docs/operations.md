# 運行與維護文檔

**English summary:** This document explains how to run, verify, and troubleshoot the RCA engine in a container-oriented environment. It covers run modes, quick API checks, runtime files, reindex flow, and the minimum verification checklist.

## 文檔目的

這份文檔聚焦在實際運行、驗證與排查 `ai-observability-rca-engine`，適合用於本地開發、demo 環境與後續部署前驗證。

## 啟動模式

服務透過 `RCA_MODE` 控制主入口行為，目前支援：

- `worker`：只啟動 Kafka consumer 與分析主循環
- `api`：只啟動 FastAPI
- `all`：同時啟動 worker 與 API，worker 在背景執行

若沒有特別理由，建議本地驗證與 demo 環境使用 `all`。

## 容器方式運行

這個項目預期在容器內運行，而不是依賴宿主機上的臨時 Python 環境。

### 建置映像

```bash
docker compose -f docker-compose-java-observability-platorm.yml build ai-observability-rca-engine
```

### 在容器內執行單元測試

```bash
docker compose -f docker-compose-java-observability-platorm.yml run --rm \
  --no-deps ai-observability-rca-engine pytest
```

### 在容器內執行 lint 與 type check

```bash
docker compose -f docker-compose-java-observability-platorm.yml run --rm \
  --no-deps ai-observability-rca-engine ruff check src tests

docker compose -f docker-compose-java-observability-platorm.yml run --rm \
  --no-deps ai-observability-rca-engine mypy src
```

## API 快速驗證

API 在容器內監聽 `8000`，整體 stack 常見會映射到宿主機 `18000`。

### 基本健康檢查

```bash
curl -sS http://localhost:18000/health
curl -sS http://localhost:18000/storage/health
```

### 核心查詢

```bash
curl -sS http://localhost:18000/events/latest
curl -sS http://localhost:18000/rca/latest
curl -sS http://localhost:18000/agents/reports/latest
```

### 檢索與問答驗證

```bash
curl -sS 'http://localhost:18000/knowledge/search?q=application%20exception'

curl -sS -X POST http://localhost:18000/copilot/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is the most likely root cause?","limit":5,"mode":"auto"}'
```

### 重新建立 retrieval index

```bash
curl -sS -X POST 'http://localhost:18000/rag/reindex?limit=200'
```

## Runtime 文件與本地狀態

服務會把本地 artifact 寫到 `runtime/output`。

常見文件包括：

- `evidence.jsonl`
- `incident-candidates.jsonl`
- `rca-results.jsonl`
- `agent-reports.jsonl`
- `rag-documents.jsonl`
- `rag-query-traces.jsonl`
- `storage-errors.jsonl`

這些文件的用途通常是：

- 檢查 ingestion 與 correlation 結果
- 驗證 fallback read 是否可用
- 觀察 retrieval layer 實際索引了哪些內容

另外若存在：

- `runtime/postgres`
- `runtime/neo4j`

請把它們視為本地開發或 demo 的 runtime state，而不是源碼資產。

## Reindex Flow

以下情況建議執行 `/rag/reindex`：

- 新的 primary store 資料已經補齊
- runbook 發生變更
- historical incident 剛被 promote
- retrieval document 因修數據需要重建

## 常見排查方向

### `/health` 正常，但 retrieval 結果很弱

先檢查：

- 是否真的有 RCA result 與 agent report
- `rag-documents.jsonl` 是否已有內容
- 是否需要重新跑 `/rag/reindex`

### PostgreSQL 或 Neo4j 不可用

先檢查：

- DSN / connection settings 是否正確
- `storage-errors.jsonl` 是否有錯誤記錄
- JSONL fallback 文件是否仍持續寫入

### Kafka ingestion 看起來停住

先檢查：

- input topics 是否存在且有資料
- bootstrap server 與 consumer group 設定是否正確
- dead-letter output 是否累積 normalization failure

## 最小驗證清單

完成修改前，至少執行以下檢查：

1. 跑 unit tests
2. 跑 `ruff check src tests`
3. 跑 `mypy src`
4. 啟動服務並確認 `/health`
5. 查詢 `/knowledge/search`
6. 發送一次 `POST /copilot/chat`

由於本服務設計上會在 optional dependency 缺失時降級，因此驗證時也建議至少觀察一次 fallback path 是否仍可用。

## 與設計文檔的分工

這份文檔回答的是：

- 怎麼跑
- 怎麼驗證
- 怎麼排錯
- 哪些 runtime 文件值得看

如果你要看系統角色、數據流、RCA pipeline、fallback 策略與 retrieval boundary，請改看 [系統設計文檔](architecture.md)。

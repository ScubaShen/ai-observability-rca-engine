# ⚙️ 運行與維護 Runbook

## 目標

本文件提供本地開發、demo 與部署前驗證所需的基本操作。

---

## 啟動模式

服務透過 `RCA_MODE` 控制：

| Mode | 說明 |
| --- | --- |
| worker | 只啟動 Kafka consumer 與 RCA 分析主循環 |
| api | 只啟動 FastAPI |
| all | 同時啟動 worker 與 API，適合本地 demo |

---

## 啟動服務

```bash
docker compose up -d
```

---

## 健康檢查

```bash
curl -sS http://localhost:18000/health
curl -sS http://localhost:18000/storage/health
```

---

## 查詢事件

```bash
curl -sS 'http://localhost:18000/events/search?service=checkout&limit=50'
```

---

## 查詢 Incident

```bash
curl -sS 'http://localhost:18000/incidents/search?service=checkout&limit=50'
```

---

## 查詢 RCA

```bash
curl -sS http://localhost:18000/rca/latest
```

---

## Copilot

```bash
curl -sS -X POST http://localhost:18000/copilot/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is the most likely root cause?","limit":5,"mode":"auto"}'
```

---

## Streaming Copilot

```bash
curl -N -sS -X POST http://localhost:18000/copilot/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"question":"Explain the RCA with citations.","limit":5,"mode":"deep"}'
```

---

## 重新建立 RAG Index

```bash
curl -sS -X POST 'http://localhost:18000/rag/reindex?limit=200'
```

---

## Runtime Artifact

常見本地輸出：

```text
runtime/output/evidence.jsonl
runtime/output/incident-candidates.jsonl
runtime/output/rca-results.jsonl
runtime/output/agent-reports.jsonl
runtime/output/rag-documents.jsonl
runtime/output/rag-query-traces.jsonl
runtime/output/storage-errors.jsonl
```

用途：

- debug ingestion
- 檢查 incident correlation
- 驗證 RCA result
- 檢查 RAG indexing
- fallback read

---

## 常見問題排查

### health 正常，但 Copilot 回答弱

檢查：

- 是否已有 RCA result
- 是否已有 agent report
- 是否執行 `/rag/reindex`
- `rag-documents.jsonl` 是否有內容
- retrieval matches 是否為空

---

### Console 載入慢

檢查：

- 是否使用 server-side search
- limit 是否過大
- PostgreSQL index 是否套用
- filter 是否足夠具體

---

### Kafka ingestion 停住

檢查：

- input topics 是否存在
- bootstrap server 是否正確
- consumer group 是否正常
- dead-letter 是否累積 normalization failure

---

### PostgreSQL / Neo4j 不可用

檢查：

- DSN / connection setting
- storage health
- storage-errors.jsonl
- JSONL fallback 是否仍持續寫入

---

## 最小驗證清單

```bash
pytest
ruff check src tests
mypy src
```

以及：

```bash
curl -sS http://localhost:18000/health
curl -sS http://localhost:18000/storage/health
curl -sS 'http://localhost:18000/knowledge/search?q=application%20exception'
curl -sS 'http://localhost:18000/events/search?service=checkout&limit=50'
curl -sS 'http://localhost:18000/incidents/search?service=checkout&limit=50'
```

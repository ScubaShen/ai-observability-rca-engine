# Evaluation

本文檔說明 evaluation 模塊做了什麼、如何在 Docker 容器內操作、數據怎麼流動，以及如何判斷結果是否通過。

這套 evaluation 是 **offline deterministic eval**：使用固定的 `eval/datasets/*.jsonl` 標註數據和 `eval/fixtures/*.json` 離線資料，在不依賴 Kafka、PostgreSQL、Neo4j 或外部 LLM 的情況下，驗證 RAG 與 RCA 的 baseline 能力。

---

## 評估內容

RAG（Retrieval-Augmented Generation，檢索增強生成）評估：

- `Recall@5`：top 5 召回率，檢查標註相關內容有多少被找回。
- `MRR`（Mean Reciprocal Rank，平均倒數排名）：檢查第一個正確結果排得多靠前。
- `NDCG@5`（Normalized Discounted Cumulative Gain at 5）：檢查 top 5 的排序質量。
- `citation coverage`：引用覆蓋率，檢查回答引用是否覆蓋標註 evidence。
- `unsupported answer rate`：無證據或高風險回答比例。
- `p95 latency`：第 95 百分位延遲，檢查大部分 query 的耗時上界。

RCA（Root Cause Analysis，根因分析）評估：

- `RootCause@3`：前三個 root cause 類別命中率，檢查 RCA 結果是否命中標註類別。

---

## Docker 內操作

先在宿主機進入 repo 並啟動一次性容器 shell：

```bash
cd /Users/worker/programs/ai-observability-rca-engine
docker compose run --rm --no-deps ai-observability-rca-engine sh
```

進入容器後，工作目錄應為 `/app`。

先跑 evaluation 單測：

```bash
pytest tests/test_evaluation.py
```

再跑完整 offline eval：

```bash
python -m rca_engine.evaluation \
  --rag-dataset eval/datasets/rag_queries.jsonl \
  --rca-dataset eval/datasets/rca_queries.jsonl \
  --fixtures eval/fixtures \
  --output runtime/output/eval-local-check.json
```

查看輸出：

```bash
cat runtime/output/eval-local-check.json
```

也可以不進 shell，直接從宿主機執行：

```bash
docker compose run --rm --no-deps ai-observability-rca-engine pytest tests/test_evaluation.py
docker compose run --rm --no-deps ai-observability-rca-engine python -m rca_engine.evaluation --rag-dataset eval/datasets/rag_queries.jsonl --rca-dataset eval/datasets/rca_queries.jsonl --fixtures eval/fixtures --output runtime/output/eval-local-check.json
```

---

## 入口鏈路

`python -m rca_engine.evaluation` 並不是自動猜到 runner，而是通過 Python package 入口轉發：

```text
python -m rca_engine.evaluation
  -> src/rca_engine/evaluation/__main__.py
  -> from rca_engine.evaluation.runner import main
  -> runner.main()
  -> run_evaluation()
```

`runner.main()` 負責解析 CLI 參數，`run_evaluation()` 負責載入 dataset、建立 offline fixture store、執行 RAG/RCA eval，最後輸出 `EvaluationReport` JSON。

---

## 數據結構

Dataset 是人工標註答案：

- `eval/datasets/rag_queries.jsonl`：RAG query 標註答案，包含 query、incident、相關 document/source/evidence/runbook。
- `eval/datasets/rca_queries.jsonl`：RCA root cause 標註答案，包含 incident 與期望 root cause 類別。

Fixtures 是 offline knowledge store：

- `eval/fixtures/rag_documents.json`：RAG 可召回文檔，例如 RCA 結果、evidence summary、historical incident。
- `eval/fixtures/runbooks.json`：排障手冊。
- `eval/fixtures/events.json`：標準化 evidence events。
- `eval/fixtures/rca_results.json`：RCA 分析結果。
- `eval/fixtures/incident_graphs.json`：incident、service、dependency、event 的圖關係。
- `eval/fixtures/agent_reports.json`：agent 分析摘要。

---

## 案例：rag_checkout_exception_001

第一條 RAG case 來自 `eval/datasets/rag_queries.jsonl`：

```json
{
  "query_id": "rag_checkout_exception_001",
  "query": "How do I investigate checkout application exception?",
  "incident_id": "incident_checkout_001",
  "intent": "runbook",
  "relevant_document_ids": ["doc_checkout_rca", "doc_checkout_evidence"],
  "relevant_sources": ["rca_result", "runbook"],
  "relevant_evidence_ids": ["event_log_1", "event_trace_1"],
  "relevant_runbook_ids": ["rb-application-exception"],
  "expected_root_cause_categories": ["application"]
}
```

這條 case 的意思是：當 operator 問 checkout application exception 如何排查時，系統應該找回 checkout exception 的 RCA 文檔、evidence 文檔、application exception runbook，並引用 `event_log_1` 和 `event_trace_1`。

對應 fixture 包含：

- `rag_documents.json` 裡的 `doc_checkout_rca`。
- `rag_documents.json` 裡的 `doc_checkout_evidence`。
- `runbooks.json` 裡的 `rb-application-exception`。
- `events.json` 裡的 `event_log_1` 和 `event_trace_1`。
- `rca_results.json` 裡 `incident_checkout_001` 的 `application` root cause。

只跑第一條 RAG case 可以這樣操作：

```bash
sed -n '1p' eval/datasets/rag_queries.jsonl > /tmp/rag_first.jsonl

python -m rca_engine.evaluation \
  --rag-dataset /tmp/rag_first.jsonl \
  --rca-dataset eval/datasets/rca_queries.jsonl \
  --fixtures eval/fixtures \
  --output /tmp/eval-first.json
```

查看第一條 query 結果：

```bash
python - <<'PY'
import json

data = json.load(open("/tmp/eval-first.json"))
print(json.dumps(data["queries"][0], indent=2))
PY
```

驗收時重點看：

- `query_id` 是 `rag_checkout_exception_001`。
- `top_sources` 包含 `rca_result`、`evidence_summary`、`runbook`。
- `recall_at_5` 是 `1.0`。
- `mrr` 是 `1.0`。
- `citation_coverage` 是 `1.0`。
- `unsupported` 是 `false`。
- `verification_status` 是 `confirmed` 或 `likely`。

---

## 關鍵結果參數

- `top_refs`：取 `response.matches[:5]`，每個 match 優先用 `ref_id`，沒有則用 `attributes.document_id`，再沒有則用 `title`。
- `top_sources`：取 `response.matches[:5]` 裡每個 match 的 `source`。
- `recall_at_5`：把標註的 `relevant_document_ids`、`relevant_sources`、`relevant_evidence_ids`、`relevant_runbook_ids` 合成 `relevant_ids`，再計算 top 5 matches 命中了多少標註 ID。
- `mrr`：看 top 5 matches 裡第一個命中 `relevant_ids` 的位置；第一名命中為 `1.0`，第二名為 `0.5`，第三名為 `0.3333`。
- `ndcg_at_5`：top 5 每個位置命中記 `1`，未命中記 `0`，按排名折扣計算 DCG，再除以理想排序 IDCG。
- `citation_coverage`：取 `response.citations[].evidence_ids`，計算覆蓋了多少標註 `relevant_evidence_ids`。
- `unsupported`：如果 verifier 判定 `missing_evidence`、`hallucination_risk` 為 `high`，或有標註 evidence 但回答沒有 citations，則為 `true`。
- `verification_status`：直接取 `response.verification.status`，例如 `confirmed`、`likely`、`missing_evidence`。
- `root_cause_at_3`：取 RCA 結果前三個 `root_causes[].category`，只要命中 `expected_root_cause_categories` 就是 `1.0`，否則是 `0.0`。

---

## Baseline 驗收標準

當前 baseline 以 `runtime/output/eval-baseline.json` 為準。完整 offline eval 通過時，核心結果應包含：

```text
rag.query_count = 3
rag.recall_at_5 = 1.0
rag.mrr = 1.0
rag.citation_coverage = 1.0
rag.unsupported_answer_rate = 0.0
rca.case_count = 2
rca.root_cause_at_3 = 1.0
```

`ndcg_at_5` 用來觀察排序質量，不一定要求是 `1.0`；只要相關內容被召回但排序不是完全理想，該值就可能低於 `1.0`。

---

## Offline Eval 與線上 RAG Evaluation

兩者用途不同：

- Offline eval：執行 `python -m rca_engine.evaluation`，讀固定 `eval/datasets` 和 `eval/fixtures`，用來驗證可重現 benchmark baseline。
- 線上 RAG Evaluation：調用 `/rag/evaluations`，讀實際 query traces 和 copilot feedback，用來觀察運行中查詢的延遲、fallback、cache hit、recall source distribution 與 feedback。

線上 endpoint 示例：

```bash
curl "http://localhost:18000/rag/evaluations?limit=100"
```

如果在容器內訪問服務容器，也可以使用服務名：

```bash
curl "http://ai-observability-rca-engine:8000/rag/evaluations?limit=100"
```

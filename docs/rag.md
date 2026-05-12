# 🔍 RAG / Copilot 設計

## 目標與原則

RAG 的目標不是讓 LLM 直接猜答案，而是讓 Copilot 先找到可信 evidence，再基於 evidence 產生回答、引用與 query trace。

核心原則：

- artifact-first：索引 RCA artifact、evidence summary、runbook、historical incident 與 graph context，而不是直接索引全部 raw logs。
- deterministic-first：召回、排序、驗證與 fallback 必須在 LLM 不可用時仍能工作。
- LLM optional：LLM synthesis / rerank 只屬於 deep path enhancement，不取代 deterministic ranking。
- every turn grounded：每一輪回答都必須 fresh retrieval、citation selection、verification 與 query trace。
- safety first：缺 evidence 時應降級為 manual investigation answer，不硬生成結論。

核心流程：

```text
Evidence Artifacts → Hybrid Retrieval → Ranking → Context → Answer → Verification → Trace
```

---

## 端到端流程

```text
User / API
  ↓
Query Orchestrator
  ↓
Query Preprocessor
  ├─ Entity Extractor
  ├─ Intent Classifier
  ├─ Bounded Query Rewriter
  └─ Drift Checker
  ↓
Retrieval Orchestrator
  ├─ Exact Lookup
  ├─ Keyword / BM25
  ├─ Vector Search
  ├─ Incident / RCA Store
  ├─ Graph Context
  └─ Runbook Retrieval
  ↓
Candidate Processor
  ├─ Dedupe
  ├─ Source Attribution
  ├─ Score Normalization
  └─ Merge
  ↓
Ranker
  ├─ Weighted Ranker for v1
  └─ RRF / LTR as evolution
  ↓
Optional Reranker
  ├─ Cross-Encoder or LLM Rerank
  └─ Deterministic Fallback
  ↓
Context Builder
  ├─ Citation Snippet Selector
  ├─ Source Diversity
  └─ Evidence Coverage Check
  ↓
Answer Generator
  ├─ Template Answer
  └─ LLM Synthesis
  ↓
Verifier
  ├─ Citation Coverage
  ├─ Evidence Consistency
  ├─ Missing Evidence
  └─ Automation Safety
  ↓
Response + Query Trace
```

這條流程的重點是把「找資料」、「排序」、「選上下文」、「生成答案」、「驗證安全性」拆開。每一層都能測試、追蹤、替換與降級。

---

## 1. Query Orchestrator

Query Orchestrator 負責承接 API / Console / future session input，決定本輪查詢使用 fast、deep 或 fallback path。

輸入：

- user question
- optional incident_id
- mode: fast / deep / auto
- session metadata

輸出：

- processed query
- selected response path
- query trace root

v1 選型：

- 保持 `CopilotRequest` 的 API shape。
- `auto` 根據 intent 與 LLM availability 選 fast / deep。
- cache hit 也要記錄 query trace。

擴展點：

- multi-turn session state
- tenant / team policy
- latency budget based routing

---

## 2. Query Preprocessor

Query Preprocessor 的目標是理解問題，而不是替使用者重寫成另一個問題。

子模組：

| 模組 | 職責 |
| --- | --- |
| Entity Extractor | 抽取 incident_id、service、env、trace_id、span_id、error code |
| Intent Classifier | 判斷 root_cause、evidence、runbook、postmortem、similar_incident |
| Bounded Query Rewriter | 只補充保守 token，不刪除原始 query 關鍵 entity |
| Drift Checker | 檢查 rewrite 是否遺失原始 entity 或大幅偏離原 query |

v1 選型：

- rule-based extractor / classifier。
- bounded rewrite 只追加 service/env/incident/error 等 token。
- drift detected 時回退原始 query。

問題點：

- query rewrite 可能刪掉 incident_id、trace_id、error code。
- LLM rewrite 可能把 operator 的追問改成看似合理但不可驗證的新問題。

擴展點：

- model-assisted intent classifier
- service catalog alias resolver
- multi-turn follow-up resolver

---

## 3. Retrieval Orchestrator

Retrieval Orchestrator 負責多路召回。RCA 場景不能只依賴 vector search，因為 incident id、error code、exception name、runbook keyword 往往更適合 exact / keyword search。

| 查詢類型 | 召回方式 |
| --- | --- |
| incident_id / trace_id / document_id | exact lookup |
| exception / error code / service name | keyword / PostgreSQL full-text |
| 相似事故 | vector search / historical incident |
| 依賴關係 / 傳播路徑 | graph context |
| 排查步驟 | runbook retrieval |
| 已生成 RCA | incident / RCA store |

v1 選型：

- 使用現有 artifact-first RAG documents。
- keyword 目前是 PostgreSQL full-text / token overlap baseline。
- vector 使用現有 hash embedding 作為可重現 baseline，不宣稱 production embedding。
- graph context 作為 incident-scoped 補充召回。

擴展點：

- production embedding provider
- OpenSearch / Elasticsearch / Tantivy BM25
- graph hop expansion
- source-specific retrieval budget

---

## 4. Candidate Processor

Candidate Processor 負責把不同 retrieval source 的結果整理成可排序候選。

職責：

- dedupe：合併同 source/ref_id/document_id 的重複候選。
- source attribution：保留候選來自 exact、keyword、semantic、graph、runbook 等來源。
- score normalization：把各召回器分數收斂到可比較區間。
- merge：合併 score breakdown、attributes、recall sources。

為什麼需要：

> 不同 retrieval source 的 score 不可直接比較。Vector cosine、keyword rank、exact match、graph clue 都有不同語義，必須先標準化和保留分數拆解。

v1 選型：

- deterministic normalization。
- 保留 `score_breakdown` 與 `recall_sources`。
- query trace 記錄 source counts 與 recall source distribution。

擴展點：

- source-specific calibration
- per-intent candidate budget
- duplicate clustering by canonical incident / evidence id

---

## 5. Ranker

Ranker 負責把候選排序，不負責刪除所有非主 intent 的資料。

v1 weighted ranker 考慮：

- semantic score
- keyword score
- exact match
- source priority
- service / env match
- incident match
- evidence strength
- intent match
- severity

設計原則：

> 先多召回，再用排序降權，而不是太早誤砍資料。

v1 選型：

- weighted deterministic ranker。
- 分數必須可拆解。
- LLM 不參與核心 ranking。

擴展點：

- RRF fusion
- learning-to-rank
- feedback-aware rank adjustment
- calibrated confidence

---

## 6. Optional Reranker

Optional Reranker 只在 deep path 使用，用來把 top-N 候選重新排序。

可選方案：

- cross-encoder rerank
- LLM rerank
- domain-specific rerank model

v1 選型：

- optional LLM rerank，預設關閉。
- rerank 失敗或不可用時使用 deterministic fallback。
- rerank strategy 必須寫入 query trace。

問題點：

- LLM rerank 不穩定。
- 成本與 latency 較高。
- 沒有 benchmark 時，很難證明 rerank 真的提升 quality。

擴展點：

- top 20 → top 5 cross-encoder
- rerank budget by mode
- rerank regression dataset

---

## 7. Context Builder

Context Builder 決定哪些 evidence 會進入回答上下文與 citation。

職責：

- citation snippet selector：從候選 content 中選短引用片段。
- source diversity：避免所有 citation 來自單一 source。
- evidence coverage check：檢查 expected / available evidence 是否被 citation 覆蓋。

v1 選型：

- 從 ranked matches 選 top citation。
- 優先保留不同 source。
- citation quote 使用短 snippet，不直接輸出長 artifact。

擴展點：

- claim-level evidence selection
- per-source citation quota
- snippet compression
- evidence coverage scoring

---

## 8. Answer Generator

Answer Generator 有兩條路：

```text
fast path
  → template answer
  → citations
  → verification

deep path
  → optional rerank
  → LLM synthesis
  → verification

fallback path
  → deterministic manual-investigation answer
```

v1 選型：

- Template answer 是正式能力，不是錯誤狀態。
- LLM synthesis 必須只使用 retrieved context。
- LLM 空回覆、不可用或違反安全規則時降級 fallback。

擴展點：

- structured LLM output
- postmortem draft
- operator-specific answer templates
- answer style policy

---

## 9. Verifier

Verifier 負責回答後檢查，避免 Copilot 把 weak evidence 講成 confirmed root cause。

檢查項：

- citation coverage
- evidence consistency
- missing evidence
- automation safety

Automation safety 必須阻止：

- auto rollback
- auto restart
- auto scale
- execute ticket
- create ticket automatically

v1 選型：

- deterministic citation / safety checks。
- 缺 citations 或 evidence weak 時降低 confidence。
- forbidden automation language 觸發 fallback manual answer。

擴展點：

- claim-level faithfulness evaluation
- contradiction detection
- policy-aware safety verifier

---

## 10. Response + Query Trace

Response 給 operator，Query Trace 給 debug、evaluation 與 feedback loop。

Response 包含：

- answer
- confidence
- matches
- citations
- verification
- response_path
- suggested_followups

Query Trace 包含：

- original / rewritten query
- extracted entities
- intent
- retrieval source counts
- candidate processing summary
- ranker score breakdown
- selected citations
- verification result
- fallback reason
- latency / token usage

重要原則：

> Query Trace 是可觀測性資料，不應被當成下一輪回答的事實來源。下一輪仍必須 fresh retrieval。

---

## 為什麼不是 Raw-Log RAG

系統不直接把 raw logs 全部丟進向量庫，原因是：

- raw logs 噪音高
- log 行通常缺少完整 incident context
- 向量檢索容易被重複錯誤訊息污染
- operator 真正需要的是已整理過的 evidence / RCA / runbook
- raw telemetry 需要先經過 normalization、signal extraction、incident correlation

因此採用 artifact-first indexing。

主要索引來源：

- runbook
- RCA result
- evidence summary
- RCA agent report
- promoted historical incident
- graph context

---

## 主要問題點

| 問題 | 風險 | 對策 |
| --- | --- | --- |
| raw-log RAG | 噪音高、context 不完整 | artifact-first indexing |
| 單一路徑 vector search | 漏掉 incident id、error code、runbook | exact + keyword + vector + graph |
| query rewrite 漂移 | 刪掉關鍵 entity | bounded rewrite + drift checker |
| LLM rerank 不穩定 | 排序不可重現 | deterministic ranker first |
| citation coverage 不足 | 答案看似合理但無證據 | verifier 降級 |
| automation language | 產生危險操作建議 | automation safety check |
| 沒有 benchmark | 無法證明 quality 提升 | offline eval dataset + runner |

---

## 選型

| 決策 | v1 選型 | 原因 | 演進 |
| --- | --- | --- | --- |
| Query preprocess | rule-based | 可測、可解釋、低風險 | model-assisted classifier |
| Query rewrite | bounded append-only | 防止 drift | multi-turn resolver |
| Keyword retrieval | PostgreSQL full-text / token baseline | 現有系統可落地 | BM25 provider |
| Vector retrieval | hash embedding baseline | 可重現、無外部依賴 | production embedding |
| Ranking | weighted deterministic | 可拆解、可降級 | RRF / LTR |
| Rerank | optional deep path | 控制成本與 latency | cross-encoder |
| Answer | template + optional LLM | LLM 不可用仍能回答 | richer synthesis |
| Verification | deterministic checks | 安全、可測 | faithfulness evaluator |

---

## 版本演進

### Current / v0 Baseline

目前已具備：

- artifact-first indexing
- hybrid retrieval skeleton
- deterministic weighted ranker
- optional LLM synthesis / rerank
- citation + verification
- query trace + feedback

但仍缺少完整獨立的 query preprocess、candidate processing、context building 與 offline benchmark。

### V1: Deterministic Production Pipeline

V1 目標：

- Query Preprocessor
- Candidate Processor
- Context Builder
- pipeline trace
- offline eval dataset + runner

V1 不追求 80% 指標，只產生可重現 baseline。

### V2: Retrieval Quality Evolution

V2 目標：

- production embedding provider
- BM25 provider
- RRF fusion
- larger benchmark dataset
- retrieval quality tuning

到 V2 才能開始誠實描述：

```text
Recall@5 improved from X to Y on internal eval set.
```

### V3: Learned / Calibrated System

V3 目標：

- learning-to-rank
- cross-encoder rerank
- probabilistic confidence calibration
- claim-level faithfulness evaluation
- feedback-driven dataset growth

到 V3 才適合使用：

```text
learned ranking
calibrated confidence
RootCause@3
```

---

## 評測與驗收

詳細操作、指標縮寫與 baseline 驗收標準見 [Evaluation](evaluation.md)。

RAG 評測：

- Recall@5
- MRR
- nDCG@5
- citation coverage
- unsupported answer rate
- p95 latency

RCA 評測：

- RootCause@3
- evidence coverage
- missing evidence rate

第一版 evaluation dataset 使用人工標註 JSONL：

```json
{
  "query_id": "rag_checkout_exception_001",
  "query": "How do I investigate checkout application exception?",
  "incident_id": "incident_checkout_001",
  "intent": "runbook",
  "relevant_document_ids": ["doc_checkout_rca"],
  "relevant_sources": ["rca_result", "runbook"],
  "relevant_evidence_ids": ["event_log_1", "event_trace_1"],
  "relevant_runbook_ids": ["rb-application-exception"],
  "expected_root_cause_categories": ["application"]
}
```

重要原則：

> 沒有 benchmark 前，不宣稱 Recall@5 80% 或 RootCause@3 80%。先建立 baseline，再證明提升。

---

## Multi-turn Conversation 狀態

目前系統已具備：

- Copilot chat
- query trace
- feedback collection
- session-level observability API

但嚴格來說，尚未完整實作真正的 multi-turn conversation memory。

真正 multi-turn 需要：

```text
load session
  → resolve active incident / service / env / intent
  → rewrite follow-up question
  → drift check
  → fresh retrieval
  → rerank
  → build citations
  → answer with verification
  → save turn
  → update session state
```

重要原則：

> Conversation history 只用來理解追問，不應被當成事實來源。每一輪回答仍必須重新 retrieval、citation verification 與 evidence grounding。

# 🔍 RAG / Copilot 設計

## 目標

RAG 的目標不是讓 LLM 自己回答，而是讓 Copilot 先找到可信 evidence，再基於 evidence 進行回答。

核心流程：

```text
Query → Retrieval → Rerank → Synthesis → Verification
```

---

## 為什麼不是 raw-log RAG

系統不直接把 raw logs 全部丟進向量庫，原因是：

- raw logs 噪音高
- log 行通常缺少完整 incident context
- 向量檢索容易被重複錯誤訊息污染
- operator 真正需要的是已整理過的 evidence / RCA / runbook

因此採用 artifact-first indexing。

---

## Indexing 來源

RAG 主要索引：

- runbook
- RCA result
- evidence summary
- RCA agent report
- promoted historical incident
- graph context

這些 artifact 比 raw telemetry 更接近值班排查語境。

---

## Hybrid Retrieval

召回方式包含：

| 查詢類型                   | 召回方式                         |
| ---------------------- | ---------------------------- |
| incident_id / trace_id | exact lookup                 |
| exception / error code | keyword / full-text          |
| 相似事故                   | vector / historical incident |
| 依賴關係 / 傳播路徑            | graph context                |
| 排查步驟                   | runbook retrieval            |

這種多路召回能避免單一向量檢索的盲點。

---

## Rerank

Rerank 使用 deterministic score，考慮：

- semantic score
- keyword score
- exact match
- source priority
- service / env match
- incident match
- evidence strength
- intent match
- severity

LLM rerank 可以作為 deep path 的 optional enhancement，但不應取代 deterministic ranking。

---

## Query Intent

系統可根據問題判斷大致 intent，例如：

- root_cause
- evidence
- runbook
- postmortem
- similar_incident

Intent 不直接刪除其他候選，而是在 rerank 時調整權重。

設計原則：

> 先多召回，再用排序降權，而不是太早誤砍資料。

---

## Fast / Deep / Fallback Path

```text
fast
  → retrieval
  → deterministic answer

deep
  → retrieval
  → optional LLM rerank
  → LLM synthesis
  → verification

fallback
  → deep path 失敗
  → deterministic answer
```

Fast path 是地基，確保 LLM 不可用時 Copilot 仍能回答。

---

## Verification

Copilot 回答需要檢查：

- citation coverage
- hallucination risk
- missing evidence
- forbidden automation language

如果回答缺少 evidence 或包含自動處置語義，系統應降級為 deterministic manual-investigation answer。

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
  → fresh retrieval
  → rerank
  → answer with citations
  → save turn
  → update session state
```

重要原則：

> Conversation history 只用來理解追問，不應被當成事實來源。每一輪回答仍必須重新 retrieval、citation verification 與 evidence grounding。

---

## 如何提升召回品質

1. Artifact-first indexing
2. RCAResult 拆成 rca_result 與 evidence_summary
3. exact + keyword + vector + graph 多路召回
4. intent-aware rerank
5. query trace 與 feedback loop
6. evaluation metrics 觀察 recall source distribution、fallback rate、latency

---

## 演進方向

- query rewrite for multi-turn follow-up
- better embedding provider
- LLM-assisted bounded rerank
- retrieval benchmark dataset
- answer faithfulness evaluation

# 系統設計文檔

**English summary:** This document describes the engineering boundaries of the RCA engine, including the data flow, event model, incident correlation, deterministic RCA pipeline, storage fallback, retrieval boundary, and failure handling. The main audience is maintainers and contributors who need to understand how the service is structured.

## 文檔目的

這份文檔說明 `ai-observability-rca-engine` 的工程邊界與主流程設計，重點不是逐行解釋程式碼，而是回答以下問題：

- 這個服務在整體系統中的角色是什麼
- 它如何處理 telemetry 並產生 RCA 結果
- 各子模組的責任邊界如何劃分
- 為什麼要保留 fallback 與 deterministic path

## 系統角色

這個引擎位於 raw observability telemetry 與 operator workflow 之間，負責把原始訊號轉成更容易理解、查詢與驗證的 incident 分析結果。

它的主要責任包括：

- 把原始 telemetry 正規化成共享事件模型
- 抽取高價值 operational signals
- 將分散事件關聯成 incident candidate
- 透過 deterministic RCA pipeline 產生 RCA 結果
- 產生 operator-facing report、runbook context 與 retrieval artifact

它的非目標包括：

- 不負責執行自動修復
- 不負責充當通用 orchestration platform
- 不依賴外部模型供應商才能完成基本流程

## 數據處理流程

```text
Kafka raw topics
  -> normalize payloads
  -> extract high-value events
  -> save event evidence
  -> correlate incidents
  -> analyze incident context
  -> persist RCA result
  -> generate operator report
  -> index artifacts for retrieval
```

主 intake 路徑實作在 [workers/kafka_worker.py](/Users/worker/programs/ai-observability-rca-engine/src/rca_engine/workers/kafka_worker.py)。

這條鏈路的設計重點是：每筆輸入都能產生可追蹤的中間結果，而不是直接跳到最終回答。這樣可以保留可觀察性與可驗證性。

## 共享事件模型

所有 high-value events 都會整理成 `NormalizedEvent`，模型位於 [src/rca_engine/models/events.py](/Users/worker/programs/ai-observability-rca-engine/src/rca_engine/models/events.py)。

這個模型的作用是讓 ingestion、correlation、storage、RCA、retrieval 使用同一套事件語義，而不需要下游直接理解原始 OTLP payload。

核心特徵包括：

- 穩定的 `event_id`
- 明確的 `event_type`
- 用於聚合與路由的 `service`、`env`、`severity`
- 可用於串接 trace 的 `trace_id`、`span_id`
- 可延伸的 `attributes`
- 可追查來源的 `evidence_refs`

## Incident Correlation

correlator 的責任是決定「哪些訊號應該被視為同一個 incident candidate」，而不是直接決定 root cause。

目前主要依據：

- service
- environment
- trace metadata
- time window
- severity hints

這樣的拆分有兩個好處：

- ingestion heuristic 與 RCA heuristic 可以獨立演進
- incident grouping 與 root cause reasoning 不會糾纏在一起

## Deterministic RCA Pipeline

`RCAOrchestrator` 只負責把整個 RCA pipeline 串起來，真正的推理規則分散在 `rca/` 子模組中。

主要步驟包括：

- load incident context
- build timeline
- classify evidence
- inspect service dependencies
- build causal links
- generate root-cause hypotheses
- rank hypotheses

這種設計讓 orchestrator 本身保持薄，避免它同時承擔流程控制與業務推理。

## 儲存層與 Fallback 策略

儲存組裝邏輯位於 [storage/composite.py](/Users/worker/programs/ai-observability-rca-engine/src/rca_engine/storage/composite.py)。

各儲存角色如下：

- JSONL：永遠存在的本地 artifact store，用於 debug 與 fallback read
- PostgreSQL：主結構化查詢儲存，承接 event、incident、report、retrieval document、feedback trace
- Neo4j：incident graph 與 causal relationship 的圖投影

fallback 原則如下：

- 寫入時先嘗試主儲存
- JSONL 仍會保留可檢查的本地輸出
- 讀取時若主儲存不可用或未配置，則回退到 JSONL

這是一種 resiliency pattern，不是 multi-primary replication 設計。

## Retrieval 邊界

retrieval 層的目標是協助 operator investigation，而不是做 autonomous action。

它結合：

- exact / structured lookup
- deterministic embedding-based search
- reranking
- evidence verification
- optional LLM synthesis

系統要求 deterministic path 本身就能回答基本問題，LLM 只能作為加強，而不能是必要前提。

## Failure Handling

目前的失敗處理策略偏保守，重點是降級而不是硬失敗：

- malformed payload 會進 dead-letter output
- backing store 不可用時會記錄錯誤並切換到 fallback path
- 若生成內容出現 blocked automation language，則強制走 deterministic fallback

這樣做的目的，是在 optional subsystem 不可用時，仍然保留最小可操作能力。

## 模組責任總覽

- `workers/`：主 intake 與端到端串接
- `processors/`：把 raw telemetry 轉成 high-value events
- `rca/`：deterministic incident reasoning
- `storage/`：structured store 與 fallback store
- `rag/`：retrieval、ranking、verification、optional synthesis
- `agents/`：operator-facing analysis、runbook recommendation、notification draft
- `console/`：內部 RCA Console

## 與運行文檔的分工

這份文檔回答的是「為什麼這樣設計」與「各部分負責什麼」。

如果你要看：

- 如何啟動
- 如何驗證
- 如何排查故障
- 如何 reindex

請改看 [運行與維護文檔](operations.md)。

# RAG / Copilot 技術設計

本文說明 Copilot RAG 如何把 RCA artifact、runbook、歷史案例與 incident graph 轉成可檢索、可引用、可降級的回答上下文。

RAG 是 Copilot 的知識層，不是使用者需要操作或改造的功能。它不追求「把所有資料丟進向量庫」，而是讓回答對齊 operator 排查語境，並能回答：

> 這個判斷根據哪些 evidence？

Evaluation 流程見 [Evaluation](evaluation.md)；回答安全邊界見 [Security](security.md)。

---

## 目標與邊界

RAG 的目標是讓 Copilot 回答可引用、可追溯、可降級。

- 可引用：關鍵判斷能連回 RCA evidence、timeline、runbook 或 historical incident。
- 可追溯：每次查詢能回放 retrieval、ranking、context selection 與 verification。
- 可降級：向量檢索、LLM 或部分 storage 不可用時，仍能給出保守回答。

RAG 不重新計算 root cause，也不替代 RCA engine。RCA engine 產生 evidence 與 hypothesis；RAG 負責把這些 artifact 變成適合問答的知識上下文。

---

## 整體設計

RAG 採用 artifact-first，而不是 raw-telemetry-first。

```text
RAG Flow
   |
   +--> Index：把 RCA artifact 切成 typed chunks
   +--> Understand：辨識 query intent 與關鍵 entity
   +--> Plan：選擇 exact / keyword / semantic / graph 等召回路徑
   +--> Retrieve：多通道召回候選文件
   +--> Rank：融合多通道排序與 domain signal
   +--> Context：選出可引用上下文
   +--> Answer：產生 fast / deep / fallback 回答
   +--> Verify：檢查 citation 與 unsafe automation language
```

Raw logs、metrics、traces 噪音高且粒度不一致。RCA artifact 已經經過 normalization、correlation、evidence scoring 與 graph projection，更適合作為回答依據。

---

## 知識建模與 Chunk 設計

Chunk 的粒度不是固定 token size，而是「operator 可以引用的一個判斷單位」。每個 chunk 保留 incident、service、env、time range、evidence id 等 metadata，讓 retrieval 與 citation 能回到具體證據。

| Chunk type | 用途 | 設計取捨 |
| --- | --- | --- |
| `evidence_log` | 錯誤訊息、exception、錯誤碼 | 適合 keyword / exact recall，但需依賴 RCA scoring 過濾噪音 |
| `evidence_metric` | latency、error rate、queue、resource anomaly | 適合回答「什麼指標異常」，單獨不推論根因 |
| `evidence_trace` | slow span、trace error、dependency span | 適合連接服務與下游依賴，但仍只是 evidence |
| `timeline_event` | incident 內事件順序 | 用於先後關係與第一個異常訊號 |
| `graph_edge` | dependency insight 與可疑關係 | 提供依賴線索，不代表強因果證明 |
| `runbook_step` | 人工排查步驟 | 作排查建議，不當成本次 incident evidence |
| `agent_finding` | specialist finding 與 follow-up | 補充專家觀察，仍需 citation 與 verification |

不使用整篇 incident report 作為唯一 chunk，因為長文會混合 root cause、timeline、evidence 與建議，難以精準引用；也不直接索引每條 raw log，避免候選集合被低價值噪音淹沒。

---

## Query Understanding 與意圖識別

Query understanding 的任務不是把問題改寫得更漂亮，而是保住精確線索，並判斷應該優先查哪一類知識。

```text
Query Understanding
   |
   +--> Intent：root cause、證據、runbook、歷史案例或 postmortem
   +--> Entity：incident id、trace id、error code、endpoint、metric、dependency
   +--> Rewrite：只做 bounded append，不改掉原始 query
   +--> Drift check：確保 entity 沒有在改寫後遺失
```

目前採 deterministic keyword / regex / bounded rewrite，讓同一個 query 可以重放出同一個 retrieval plan，也方便 regression test。

| Intent | 問題類型 | Retrieval 偏好 |
| --- | --- | --- |
| `root_cause` | 最可能根因是什麼 | RCA artifact、current evidence、graph |
| `evidence` | 有哪些證據支持判斷 | current evidence、timeline |
| `runbook` | 接下來怎麼人工排查 | runbook step、相關 evidence |
| `similar_incident` | 有沒有相似歷史問題 | historical incident、semantic |
| `postmortem` | 如何整理事故敘述 | RCA artifact、timeline、citation context |
| `general` | 未明確分類的問題 | keyword、semantic、artifact |

不在第一版使用 LLM intent classifier 或自由 rewrite，原因是可測試性、漂移風險、成本與可重放性。LLM 可以演進為 bounded expansion 或 rerank，但不應取代 deterministic parsing。

---

## Retrieval Plan 與多通道召回

RCA 查詢常同時包含精確 id、錯誤碼、模糊症狀、服務別名、歷史案例與依賴關係；單一 vector search 很難同時滿足 precision 與 recall。

```text
Query Plan
   |
   +--> Exact：指定 incident id / runbook id
   +--> Keyword：錯誤碼、exception、服務名
   +--> Semantic：模糊症狀、別名、中英文混合描述
   +--> Runbook：排查手冊
   +--> History：歷史問題
   +--> Graph：有依賴關係
```

Exact / Keyword 保住精確線索，Semantic 補足模糊描述與 domain expansion。Runbook 與 History 獨立召回，避免把人工建議或歷史案例誤當成本次 incident evidence。Graph 只提供 dependency clue，需要和 evidence、timeline、trace signal 一起解讀。

---

## Ranking、Context 與 Answer Grounding

多通道召回後，候選文件會去重、合併 recall sources，再做融合排序。RRF 用來降低單一 channel 偏差，偏好多個 channel 都命中的候選。

```text
Ranking & Grounding
   |
   +--> normalize score
   +--> dedupe same source / ref
   +--> merge recall sources
   +--> RRF fusion
   +--> domain boost
   +--> context selection
   +--> citation with source / ref / evidence ids
   +--> verification
   +--> fallback when evidence is missing or unsafe
```

Domain boost 反映 RCA 場景的基本優先級：同 service、同 env、同 incident 的 evidence 更靠前；runbook intent 提高 runbook source；similar incident intent 提高 historical source。

若缺少 citation、證據不足，或出現自動 rollback / restart / scale 等不安全語言，系統會降級成更保守的 manual investigation answer。

---

## 設計取捨

| 決策 | 好處 | 代價 |
| --- | --- | --- |
| artifact-first RAG | 降低 raw telemetry 噪音，回答更接近 RCA 語境 | artifact 品質會影響召回品質 |
| typed chunk | citation 精準，retrieval 可依 intent 選資料 | chunk schema 需要隨 RCA artifact 演進 |
| deterministic query understanding | 可測試、可重放、低成本 | 對自然語言變體的覆蓋需要持續補強 |
| hybrid retrieval | 同時保住 precision 與 recall | retrieval trace 與 ranking 邏輯較複雜 |
| runbook / history 分離 | 避免把建議或歷史案例誤當證據 | 回答需要清楚區分 evidence 與 reference |
| RRF + domain boost | 降低單一路徑偏差，貼近排查優先級 | boost 權重需要透過 evaluation 校正 |
| guarded answer | 減少 unsupported 或 unsafe 回答 | 在證據不足時回答會更保守 |

---

## 演進方向

RAG 的演進應由觀測結果推動，而不是一開始就引入更複雜的模型。

| 觀測信號 | 演進方向 |
| --- | --- |
| 標註 query / answer 資料穩定 | 引入 learning-to-rank，並保留 deterministic fallback |
| semantic recall 在模糊查詢上穩定提升 | 提高 embedding 權重，但保留 exact / keyword 通道 |
| unsupported answer rate 下降且 citation coverage 穩定 | 擴大 deep synthesis 使用範圍 |
| 中文 query miss rate 偏高 | 優先增強中文 entity extraction 與 domain synonym |
| historical incident 命中品質提高 | 加入 case-based recommendation，但標記為歷史參考 |

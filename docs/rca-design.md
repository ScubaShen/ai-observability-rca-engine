# 🧠 RCA 設計

## 目標

RCA 模組的目標是根據 evidence 產生可解釋的 root cause hypothesis，而不是讓 LLM 直接猜答案。

核心原則：

```text
Evidence → Reasoning → Root Cause Hypothesis
```

---

## RCA Pipeline

```text
Incident Context
  → Timeline
  → Evidence Scoring
  → Dependency Analysis
  → Causal Graph
  → Hypothesis Generation
  → Root Cause Ranking
```

---

## 1. Incident Context

Context Loader 會根據 incident candidate 收斂上下文：

- 同 service
- 同 env
- 同時間窗
- trace_id / correlation key 有交集

這樣避免 RCA 把同時間其他服務的噪音混入分析。

---

## 2. Timeline

Timeline 用來建立 incident 內事件順序。

它不是 raw payload viewer，只保留 operator 排查最常用欄位：

- event time
- event type
- service
- severity
- trace id
- error pattern
- duration
- metric value

目的：

- 快速看到第一個異常訊號
- 比較 log / metric / trace 的時間關係
- 支援後續 causal link 建立

---

## 3. Evidence Scoring

Evidence scoring 不是機率模型，而是排查排序訊號。

它回答的是：

> 哪些 evidence 更值得 operator 優先相信？

簡化公式：

```text
score =
  base_signal_confidence
  + severity_weight
  + event_type_priority
  + incident_membership_bonus
  + correlation_key_overlap
  + trace_coherence
  + cross_signal_agreement
  + change_proximity
```

---

## 設計原則

### 1. 單一訊號不應主導結論

一條 error log 或一個 metric spike 不應直接被當成 root cause。

### 2. 跨訊號一致性比單點訊號更可信

例如：

```text
trace.error + log.error_pattern + metric.anomaly
```

比單一 `log.error_pattern` 更值得相信。

### 3. 分數必須可拆解

每個 evidence 的分數都應該能回溯到具體因素，而不是黑盒輸出。

---

## 可信度區間

設計原因：

- 保留 bonus 加分空間
- 防止單一 signal 過度接近 1.0
- 方便映射到 weak / medium / strong

```text
0.00 - 0.60  weak
0.60 - 0.75  medium
0.75+        strong
```

---

## 為什麼不讓 LLM 評分

不建議把 evidence scoring 交給 LLM，原因是：

1. 不穩定：同樣輸入可能產生不同分數
2. 不可測試：難以做 deterministic regression test
3. 不可解釋：無法精準拆解每一分從何而來
4. 容易 hallucinate：可能補不存在的 evidence
5. 成本高：每個 evidence 都調 LLM 會造成延遲與費用問題

LLM 可以輔助：

- explanation
- summarization
- optional rerank
- postmortem draft

但不應成為核心 scoring engine。

---

## 4. Dependency Analysis

Dependency Analyzer 主要從 trace 類事件判斷是否存在可疑依賴，例如：

- DB
- Redis
- Kafka
- HTTP downstream service

這不是完整 service map，而是 RCA 中的 dependency clue。

---

## 5. Causal Graph

Causal graph 表達三類關係：

```text
timeline adjacency   → triggered_before
same trace id        → same_trace
suspect dependency   → possible_cause_of
```

這不是強因果推論，而是 operator 可讀的因果線索投影。

---

## 6. Hypothesis Generation

目前優先產生幾類 hypothesis：

- dependency issue
- application error / exception path
- resource or load issue
- fallback: first correlated signal

設計重點是先覆蓋微服務故障中最常見、最可觀測的根因類型。

---

## 7. Root Cause Ranking

排序依據：

- confidence
- evidence score
- supporting event count
- cross-signal agreement
- causal link strength

只保留 top-N，避免低品質 hypothesis 增加值班負擔。

---

## 演進方向

後續可升級為：

- 基於標註資料的 learning-to-rank
- graph-based score propagation
- 更完整的 change event integration
- incident replay benchmark
- calibrated confidence model

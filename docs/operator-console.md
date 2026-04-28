# 🖥️ Operator Console 設計

## 目標

RCA Console 是值班人員的排查入口，不是自動處置台。

它的目標是幫助 operator：

1. 找到需要排查的 incident
2. 檢查 timeline 與 evidence
3. 理解 RCA 結果與 causal graph
4. 使用 Copilot 做追問
5. 產生 postmortem draft

---

## 設計原則

```text
Incident First, not Chat First
```

原因是 RCA 系統不能讓使用者一進來就只看 AI 回答。使用者應先看到 incident、evidence、timeline、graph，再使用 Copilot 補充追問。

---

## 建議操作流程

```text
Incidents
  → Incident Detail
  → Overview
  → Timeline
  → Evidence
  → Graph
  → Report
  → Copilot Follow-up
  → Postmortem
```

---

## 頁面結構

### Incidents

用於搜尋與定位 incident candidate / analyzed incident。

支援條件：

- service
- severity
- updated time
- keyword
- pagination

---

### Incident Detail

單一 incident 的核心分析頁。

建議分頁：

- Overview
- Timeline
- Evidence
- Graph
- Report
- Postmortem
- Raw JSON

---

### Evidence

Evidence tab 是 RCA Console 的核心之一。

它應該展示：

- event id
- event type
- service
- severity
- confidence
- strength
- score breakdown
- citation / evidence reference

目的是讓 operator 能判斷 RCA 結論是否真的被 evidence 支持。

---

### Graph

Graph 用於展示 incident、evidence、root cause、dependency 之間的關係。

早期可以用表格呈現 nodes / relationships，不一定要先做複雜互動圖。

---

### Copilot

Copilot 用於追問，不是第一入口。

Copilot 頁面應展示：

- answer
- citations
- matches
- verification
- missing evidence
- feedback button

---

## 為什麼不用 Chat-first

Chat-first 會帶來風險：

- 使用者直接相信 LLM 回答
- 忽略 evidence 是否足夠
- 無法判斷回答是 strong hypothesis 還是 weak guess
- 容易把 AI 補充內容誤認為事實

因此 Console 必須以 incident review 為主流程。

---

## 後續演進

- 多人值班協作
- RBAC
- incident assignment
- action audit
- richer graph visualization
- multi-turn Copilot memory

# 🔐 安全與邊界設計

## 目標

本文件定義 RCA 平台中的 secret handling、LLM safety boundary、query boundary 與 automation boundary。

---

## Secret Handling

原則：

- 不要把 `LLM_API_KEY` 寫入 git
- 不要把 API key 寫入 README / docs / compose 固定值
- compose 只使用環境變數引用
- `/health` 不得輸出 key

允許顯示：

- provider name
- model name
- streaming enabled
- reasoning effort

不允許顯示：

- API key
- token
- secret header
- credential file content

---

## LLM Safety Boundary

LLM 允許：

- RCA explanation
- evidence summarization
- manual runbook recommendation
- incident summary
- postmortem draft
- follow-up questions

LLM 不允許：

- rollback executor
- restart executor
- scale executor
- ticket executor
- approval automation
- 自動處置決策

---

## Verification

Copilot 回答需要檢查：

- citation coverage
- hallucination risk
- forbidden automation language
- missing evidence

如果 LLM 產生自動執行語義，系統應丟棄該回答，並回退到 deterministic manual-investigation answer。

---

## Data Boundary

RAG context 只能來自：

- stored RCA artifacts
- runbooks
- historical incidents
- normalized events
- graph projection

不得用 LLM 補不存在的 evidence。

如果 evidence 不足，應明確說明缺口，例如：

```text
目前缺少 DB metric 或 downstream trace，無法確認是否為資料庫依賴導致。
```

---

## Query Boundary

`/events/search` 和 `/incidents/search` 是 read-only operator query API。

它們不應：

- 觸發處置
- 建立 ticket
- 修改服務狀態
- 觸發 rollback
- 改變 incident ground truth

Cursor 是 pagination token，不應被視為授權或資料隔離機制。

---

## Automation Boundary

目前系統不包含自動化處置。

若未來加入 Automation Engine，必須滿足：

- approval required
- audit log
- dry-run
- rollback plan
- blast radius control
- RBAC
- manual confirmation

在此之前，Copilot 只能推薦 manual runbook，不可直接執行。

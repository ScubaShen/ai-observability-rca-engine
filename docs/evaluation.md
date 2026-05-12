# Evaluation Guide

本文檔說明如何用 evaluation 驗證 RAG 與 RCA 的改動，並比較 baseline 與 candidate。

核心原則：

- 每次 evaluation 只跑當前 checkout 的代碼。
- baseline / candidate 是用同一份資料、同一組命令，在不同版本各跑一次後得到的兩份 report。
- dev 用來看 candidate 是否改善，holdout 用來確認改善沒有只貼合 dev cases。

---

## Evaluation 的目的

Evaluation 主要回答三個問題：

1. RAG 是否找得到正確的 incident、evidence、runbook 與上下文？
2. RCA 是否能推導出正確 root cause，並提供足夠支撐證據？
3. candidate 是否比 baseline 更好，而且沒有在重要情境退化？

因此，每次做 RAG 分片、語義召回、rerank、多輪對話、RCA ranking 或 evidence support 的升級時，都應該產生 baseline / candidate report，再用 compare 判斷結果。

---

## Dataset 怎麼用

Evaluation dataset 分成三層。三者用途不同，不應混在一起解讀。

| Split | 用途 | 什麼時候跑 | 是否用來調參 |
| --- | --- | --- | --- |
| `smoke` | 確認 pipeline 能跑通 | 開始前或 CI 健康檢查 | 否 |
| `dev` | 驗證 candidate 是否改善目標能力 | 開發期間反覆跑 | 是 |
| `holdout` | 確認 candidate 沒有只貼合 dev cases | 宣稱改善前跑 | 否 |

對應檔案：

- `smoke`：
  - `eval/datasets/rag_queries.jsonl`
  - `eval/datasets/rca_queries.jsonl`
  - `eval/fixtures/replay_events.json`
  - `eval/fixtures/runbooks.json`
- `dev`：
  - `eval/datasets/rag_queries.dev.jsonl`
  - `eval/datasets/rca_queries.dev.jsonl`
  - `eval/fixtures/replay_events.hard.json`
  - `eval/fixtures/runbooks.hard.json`
- `holdout`：
  - `eval/datasets/rag_queries.holdout.jsonl`
  - `eval/datasets/rca_queries.holdout.jsonl`
  - `eval/fixtures/replay_events.hard.json`
  - `eval/fixtures/runbooks.hard.json`

建議流程：

```text
1. 在 baseline commit 跑 dev eval
   -> runtime/output/eval-dev-baseline.json

2. 在 candidate commit 跑 dev eval
   -> runtime/output/eval-dev-candidate.json

3. compare dev
   -> 判斷 candidate 是否改善主要開發目標

4. candidate 在 dev 上看起來有效後，再跑 holdout
   -> baseline / candidate 各一份 holdout report

5. compare holdout
   -> 確認 candidate 沒有只貼合 dev cases
```

一套代碼也能比較兩個版本，因為 compare 比的是兩份 JSON report，不是同時啟動兩套程式。只要 baseline 與 candidate 使用相同 dataset、events、runbooks 與 command 參數，差異就主要來自代碼版本。

---

## 指標與結果解讀

先理解 report 中的欄位與指標，再執行命令，會更容易判斷 candidate 到底改善了哪裡。

### Dataset 欄位

RAG 與 RCA dataset 都使用人工確認的 expected labels。常見欄位如下：

- `query_id` / `case_id`：單筆評測識別。
- `dataset_split`：`smoke`、`dev` 或 `holdout`。
- `metric_slices`：分組分析標籤，例如 `hard`、`chinese_query`、`noisy_query`、`multi_signal`、`evidence_support`。
- `label_source`：答案來源，例如 reviewed incident、replay case 或人工標註。
- `review_status`：label 是否已 review。
- `relevant_document_ids`：RAG 應召回的文件或 artifact。
- `relevant_evidence_ids`：RAG 或 RCA 應命中的 evidence。
- `relevant_runbook_ids`：RAG 應召回的 runbook。
- `expected_root_cause_categories`：RCA 預期根因類型。
- `expected_root_cause`：人工確認的根因描述。

`metric_slices` 很重要。overall 分數可能掩蓋局部退化，而 slice 可以回答更具體的問題，例如中文 query 是否改善、noisy query 是否退化、多信號 RCA 是否仍能找齊 evidence。

### RAG 指標

RAG 指標主要回答「該找回來的內容有沒有找回來，以及排序是否好」。

- `Recall@5`：前 5 筆結果涵蓋多少 expected ids。適合評估分片、召回、query rewrite 是否有效。
- `Recall@10`：比 `Recall@5` 更寬鬆，能觀察內容是否至少被找回，只是排序還不夠前。
- `MRR`：第一個正確結果排得多前。適合評估 rerank 與排序品質。
- `nDCG@5`：前 5 筆排序品質。正確結果越靠前，分數越高。
- `Citation Coverage`：答案是否有足夠引用支撐。
- `Unsupported Answer Rate`：答案看似合理但缺乏支撐的比例，越低越好。

不同升級方向建議優先看：

- RAG 分片：`Recall@5`、`Recall@10`、`nDCG@5`
- 語義召回：long query、vague query、chinese query、similar incident slices
- rerank：`MRR`、`nDCG@5`
- 多輪對話：multi-turn 或 context-dependent query slices
- evidence completeness：evidence support 相關 slice 與 missed evidence ids

### RCA 指標

RCA 指標主要回答「根因是否答對，以及證據是否足夠」。

- `RootCause@1`：第一名 root cause 是否正確。這是最直接的 RCA 品質指標。
- `RootCause@3`：前三名是否包含正確 root cause。可觀察 ranking 是否至少把正解納入候選。
- `Category Accuracy`：根因類型是否正確，例如 application、dependency、resource/load。
- `Evidence Support`：supporting evidence 是否覆蓋 expected evidence。這能避免只答對分類，但缺少 log、trace、metric、deploy/config 等關鍵支撐。

RCA compare 時不能只看 root cause category。若 category 命中但 evidence support 下降，仍應視為風險，需要 review。

### Compare Report

Compare report 會把 baseline 與 candidate 的差異整理成 verdict、overall delta、slice delta、per-query improvements 與 regressions。

建議判讀順序：

1. 看 `verdict`：快速確認整體是 `improved`、`neutral`、`regressed` 或 `needs_review`。
2. 看 overall metrics：確認主要指標是否真的上升。
3. 看 dev / holdout / hard / language / intent slices：確認改善是否發生在目標能力上。
4. 看 `improvements`：確認哪些 query 或 RCA case 被 candidate 修好。
5. 看 `regressions`：確認是否有重要 case 退化。
6. 看 missed / retrieved expected ids：定位召回、排序或 evidence support 的具體問題。

常見結論：

- Dev 改善、holdout 不退：可以初步認為 candidate 有改善。
- Dev 改善、holdout 下降：需要 review，不能直接宣稱改善。
- Overall 改善、critical slice 下降：需要 review，因為平均分可能掩蓋重要退化。
- RAG recall 上升但 unsupported answer rate 上升：需要 review，可能找回更多但答案支撐變差。
- RCA category 上升但 evidence support 下降：需要 review，可能只答對分類但沒有足夠證據。

---

## 容器內執行

以下命令假設已在容器內、repo 根目錄執行。

### 1. 跑 evaluation 測試

```bash
pytest tests/test_evaluation.py
```

這一步確認 dataset schema、evaluation runner、report、compare 等基本行為正常。

### 2. 可選：跑 smoke 健康檢查

`replay` command 的主要參數：

- `--rag-dataset`：RAG labels，定義 query 應召回的文件、evidence、runbook 或 root cause。
- `--rca-dataset`：RCA labels，定義 expected root cause、category 與 supporting evidence。
- `--events`：事件輸入。
- `--runbooks`：可被 RAG 召回的操作知識。
- `--output`：單次 evaluation report 的輸出路徑。

```bash
python -m rca_engine.evaluation replay \
  --rag-dataset eval/datasets/rag_queries.jsonl \
  --rca-dataset eval/datasets/rca_queries.jsonl \
  --events eval/fixtures/replay_events.json \
  --runbooks eval/fixtures/runbooks.json \
  --output runtime/output/eval-smoke.json
```

Smoke 只回答「pipeline 是否能跑通」。它不是主要的改善驗證流程。

### 3. 在 baseline commit 跑 dev

```bash
python -m rca_engine.evaluation replay \
  --rag-dataset eval/datasets/rag_queries.dev.jsonl \
  --rca-dataset eval/datasets/rca_queries.dev.jsonl \
  --events eval/fixtures/replay_events.hard.json \
  --runbooks eval/fixtures/runbooks.hard.json \
  --output runtime/output/eval-dev-baseline.json
```

這份 report 代表線上版本或改動前版本在 dev dataset 上的表現。

### 4. 在 candidate commit 跑 dev

```bash
python -m rca_engine.evaluation replay \
  --rag-dataset eval/datasets/rag_queries.dev.jsonl \
  --rca-dataset eval/datasets/rca_queries.dev.jsonl \
  --events eval/fixtures/replay_events.hard.json \
  --runbooks eval/fixtures/runbooks.hard.json \
  --output runtime/output/eval-dev-candidate.json
```

這份 report 代表改動後版本在同一份 dev dataset 上的表現。

### 5. Compare dev

`compare` command 的主要參數：

- `--baseline`：baseline commit 產生的 report。
- `--candidate`：candidate commit 產生的 report。
- `--output`：compare report 的輸出路徑。

```bash
python -m rca_engine.evaluation compare \
  --baseline runtime/output/eval-dev-baseline.json \
  --candidate runtime/output/eval-dev-candidate.json \
  --output runtime/output/eval-dev-compare.json
```

Dev compare 用來判斷 candidate 是否改善主要開發目標。開發 RAG 分片、語義召回、rerank 或多輪對話時，這通常是最常看的 compare report。

### 6. 在 baseline commit 跑 holdout

```bash
python -m rca_engine.evaluation replay \
  --rag-dataset eval/datasets/rag_queries.holdout.jsonl \
  --rca-dataset eval/datasets/rca_queries.holdout.jsonl \
  --events eval/fixtures/replay_events.hard.json \
  --runbooks eval/fixtures/runbooks.hard.json \
  --output runtime/output/eval-holdout-baseline.json
```

### 7. 在 candidate commit 跑 holdout

```bash
python -m rca_engine.evaluation replay \
  --rag-dataset eval/datasets/rag_queries.holdout.jsonl \
  --rca-dataset eval/datasets/rca_queries.holdout.jsonl \
  --events eval/fixtures/replay_events.hard.json \
  --runbooks eval/fixtures/runbooks.hard.json \
  --output runtime/output/eval-holdout-candidate.json
```

### 8. Compare holdout

```bash
python -m rca_engine.evaluation compare \
  --baseline runtime/output/eval-holdout-baseline.json \
  --candidate runtime/output/eval-holdout-candidate.json \
  --output runtime/output/eval-holdout-compare.json
```

Holdout compare 用來確認 candidate 沒有只貼合 dev cases。若 holdout 出現重要 regression，即使 dev 有改善，也應人工 review。

---

## 如何增加新的評測案例

新增 case 的目標是讓 evaluation 更貼近真實升級需求，而不是只追求單次分數。

推薦流程：

1. 從 production query、incident ticket、on-call 記錄、postmortem 或 copilot feedback 中挑候選。
2. 人工確認 expected root cause、evidence、runbook 與相關 incident。
3. 先加入 `dev`，用於開發與調整策略。
4. 類型穩定後，再補充到 `holdout`，用於防止 overfit。
5. 使用 `metric_slices` 標記能力類型，方便 compare 時定位改善或退化。

建議覆蓋的 case 類型：

- 長句 query：測試語義理解與噪聲容忍。
- 中文 query：測試跨語言召回。
- noisy query：測試錯誤服務名、多餘症狀下的穩定性。
- multi-turn query：測試上下文延續與省略資訊補全。
- similar incident query：測試跨 incident 搜索。
- multi-signal RCA：測試 log、trace、metric、deploy/config 是否能共同支持根因。
- evidence completeness：測試不只答對 root cause，還要找齊 supporting evidence。

---

## 改善判定標準

一次 candidate 是否值得繼續推進，建議至少滿足：

- dev 的目標 slice 有正向 delta。
- holdout 沒有重要 regression。
- RAG 的 `Recall@5`、`MRR`、`nDCG@5` 至少不退。
- RCA 的 `RootCause@1`、`Category Accuracy`、`Evidence Support` 至少不退。
- `regressions` 為空，或每個 regression 都有明確可接受理由。

如果只看到 smoke 通過，不能宣稱 RAG/RCA 能力提升。Smoke 只代表流程健康；dev 和 holdout compare 才是判斷 candidate 是否真的改善的主要依據。

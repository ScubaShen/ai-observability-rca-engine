# Evaluation Guide

本文檔說明如何用 evaluation 驗證 RAG 與 RCA 的改動，並用 baseline / candidate report 判斷 candidate 是否真的改善。

Evaluation 的重點不是理解內部架構，而是確認 RAG 是否找回正確上下文、RCA 是否答對 root cause 並有證據支撐，以及 candidate 是否比 baseline 更好且沒有重要退化。

---

## 1. Evaluation 用來做什麼

每次修改 RAG 召回、排序、citation，或 RCA root cause ranking、category、evidence support 時，都建議跑 evaluation。

核心原則：

- 每次 evaluation 只跑當前 checkout 的代碼。
- baseline / candidate 是不同版本各跑一次後得到的兩份 report。
- compare 比較的是兩份 JSON report，不需要同時啟動兩套程式。
- smoke 只確認流程健康；dev / holdout compare 才能用來判斷能力是否改善。

---

## 2. 核心流程

Evaluation 的流程可以理解成：準備離線資料、評測 RAG/RCA、輸出 report、比較兩份 report。

```text
events + runbooks + datasets
    |
    v
run evaluation
    |
    +-- evaluate RAG retrieval and citations
    +-- evaluate RCA root cause and evidence
    |
    v
EvaluationReport
    |
    v
compare baseline vs candidate
    |
    v
ComparisonReport + Markdown summary
```

實際執行時主要用兩個 CLI：

- `python -m rca_engine.evaluation replay`：用一組 events、runbooks、RAG dataset、RCA dataset 產生單次 `EvaluationReport`。
- `python -m rca_engine.evaluation compare`：比較 baseline / candidate 兩份 report，產生 `ComparisonReport` 與同名 Markdown 摘要。

建議先看 compare 產生的 `.md` 摘要；JSON report 則用來追單筆 query、case、missed ids 或 slice 細節。

---

## 3. Dataset / Report / Metrics 怎麼看

Dataset 分成三種 split。三者用途不同，不應混在一起解讀。

| Split | 用途 | 什麼時候跑 | 是否用來調參 |
| --- | --- | --- | --- |
| `smoke` | 確認流程能跑通 | 開始前或 CI 健康檢查 | 否 |
| `dev` | 驗證 candidate 是否改善目標能力 | 開發期間反覆跑 | 是 |
| `holdout` | 確認 candidate 沒有只貼合 dev cases | 宣稱改善前跑 | 否 |

對應檔案：

| Split | RAG dataset | RCA dataset | Events | Runbooks |
| --- | --- | --- | --- | --- |
| `smoke` | `eval/datasets/rag_queries.jsonl` | `eval/datasets/rca_queries.jsonl` | `eval/fixtures/replay_events.json` | `eval/fixtures/runbooks.json` |
| `dev` | `eval/datasets/rag_queries.dev.jsonl` | `eval/datasets/rca_queries.dev.jsonl` | `eval/fixtures/replay_events.hard.json` | `eval/fixtures/runbooks.hard.json` |
| `holdout` | `eval/datasets/rag_queries.holdout.jsonl` | `eval/datasets/rca_queries.holdout.jsonl` | `eval/fixtures/replay_events.hard.json` | `eval/fixtures/runbooks.hard.json` |

Dataset case 重點欄位：

- `query_id`、`query`、`incident_id`：定位單筆評測。
- `dataset_split`、`metric_slices`：用來做分組分析，例如 `hard`、`chinese_query`、`noisy_query`、`evidence_support`。
- `relevant_document_ids`、`relevant_evidence_ids`、`relevant_runbook_ids`：RAG 應該找回的內容。
- `expected_root_cause_categories`、`expected_root_cause`：RCA 應該命中的根因。

`EvaluationReport` 主要看：

- `rag`：RAG overall metrics。
- `rca`：RCA overall metrics。
- `slices`：依 split、intent、語言、metric slices 等分組後的 metrics。
- `queries`：每筆 RAG query 的 top refs、retrieved / missed expected ids、citation 與 verification。
- `rca_cases`：每筆 RCA case 的 top categories、supporting / missed evidence ids。

`ComparisonReport` 主要看：

- `verdict`：整體是 `improved`、`neutral`、`regressed` 或 `needs_review`。
- `overall_delta`：overall 指標差異。
- `slice_delta`：共同 slice 上的指標差異。
- `regressions` / `improvements`：單筆 query 或 RCA case 的退化與改善。
- `acceptance`：Advanced RAG focus slices 與 guardrails 的驗收摘要。

常用 metrics 如下：

| 指標 | 用途 |
| --- | --- |
| `recall_at_5` / `recall_at_10` | RAG 是否找回 expected ids。 |
| `mrr` | 第一個正確結果排得多前。 |
| `ndcg_at_5` | 前 5 筆排序品質。 |
| `citation_coverage` | 答案引用是否覆蓋 expected evidence。 |
| `unsupported_answer_rate` | RAG 答案缺乏支撐的比例，越低越好。 |
| `root_cause_at_1` / `root_cause_at_3` | RCA top 1 / top 3 是否命中 expected category。 |
| `evidence_support` | RCA supporting evidence 是否覆蓋 expected evidence。 |
| `unsupported_root_cause_rate` | RCA 結論缺乏支撐的比例，越低越好。 |

---

## 4. Baseline vs Candidate 怎麼比較

建議流程：

```text
1. 在 baseline commit 跑 dev
   -> runtime/output/eval-dev-baseline.json

2. 在 candidate commit 跑 dev
   -> runtime/output/eval-dev-candidate.json

3. compare dev
   -> 判斷 candidate 是否改善開發目標

4. dev 看起來有效後，再跑 baseline / candidate 的 holdout

5. compare holdout
   -> 確認 candidate 沒有只貼合 dev cases
```

判讀順序：

1. 先看 compare 產生的 Markdown 摘要。
2. 看 `verdict`：快速判斷整體改善、持平、退化或需要人工 review。
3. 看 `acceptance.verdict`：確認 Advanced RAG focus slices 是否通過。
4. 看 `overall_delta` 與 `slice_delta`：確認改善是否發生在目標能力上。
5. 看 `regressions`：確認重要 query 或 RCA case 是否退化。
6. 若需要定位問題，再看 `missed_expected_ids`、`retrieved_expected_ids`、`supporting_evidence_ids`、`missed_evidence_ids`。

常見結論：

- Dev 改善、holdout 不退：可以初步認為 candidate 有改善。
- Dev 改善、holdout 下降：需要 review，不能直接宣稱改善。
- Overall 改善、critical slice 下降：需要 review，平均分可能掩蓋重要退化。
- RAG recall 上升但 `unsupported_answer_rate` 上升：需要 review。
- RCA category 上升但 `evidence_support` 下降：需要 review。
- `acceptance.verdict = failed`：focus slice 排序/召回退步，或 unsupported rate 上升。
- `acceptance.verdict = passed`：focus slice 有改善且 guardrails 不退。

---

## 5. 常用命令與改善標準

以下命令假設已在容器內、repo 根目錄執行。

### 測試 evaluation 行為

```bash
pytest tests/test_evaluation.py
```

### Smoke 健康檢查

```bash
python -m rca_engine.evaluation replay \
  --rag-dataset eval/datasets/rag_queries.jsonl \
  --rca-dataset eval/datasets/rca_queries.jsonl \
  --events eval/fixtures/replay_events.json \
  --runbooks eval/fixtures/runbooks.json \
  --output runtime/output/eval-smoke.json
```

### Dev baseline / candidate

```bash
python -m rca_engine.evaluation replay \
  --rag-dataset eval/datasets/rag_queries.dev.jsonl \
  --rca-dataset eval/datasets/rca_queries.dev.jsonl \
  --events eval/fixtures/replay_events.hard.json \
  --runbooks eval/fixtures/runbooks.hard.json \
  --output runtime/output/eval-dev-baseline.json
```

```bash
python -m rca_engine.evaluation replay \
  --rag-dataset eval/datasets/rag_queries.dev.jsonl \
  --rca-dataset eval/datasets/rca_queries.dev.jsonl \
  --events eval/fixtures/replay_events.hard.json \
  --runbooks eval/fixtures/runbooks.hard.json \
  --output runtime/output/eval-dev-candidate.json
```

```bash
python -m rca_engine.evaluation compare \
  --baseline runtime/output/eval-dev-baseline.json \
  --candidate runtime/output/eval-dev-candidate.json \
  --output runtime/output/eval-dev-compare.json
```

### Holdout baseline / candidate

```bash
python -m rca_engine.evaluation replay \
  --rag-dataset eval/datasets/rag_queries.holdout.jsonl \
  --rca-dataset eval/datasets/rca_queries.holdout.jsonl \
  --events eval/fixtures/replay_events.hard.json \
  --runbooks eval/fixtures/runbooks.hard.json \
  --output runtime/output/eval-holdout-baseline.json
```

```bash
python -m rca_engine.evaluation replay \
  --rag-dataset eval/datasets/rag_queries.holdout.jsonl \
  --rca-dataset eval/datasets/rca_queries.holdout.jsonl \
  --events eval/fixtures/replay_events.hard.json \
  --runbooks eval/fixtures/runbooks.hard.json \
  --output runtime/output/eval-holdout-candidate.json
```

```bash
python -m rca_engine.evaluation compare \
  --baseline runtime/output/eval-holdout-baseline.json \
  --candidate runtime/output/eval-holdout-candidate.json \
  --output runtime/output/eval-holdout-compare.json
```

新增 case 時：

- 從 production query、incident ticket、on-call 記錄、postmortem 或 copilot feedback 中挑候選。
- 人工確認 expected root cause、evidence、runbook 與相關 incident。
- 先加入 `dev`，穩定後再補到 `holdout`。
- 用 `metric_slices` 標記能力類型，例如 `chinese_query`、`noisy_query`、`runbook_discrimination`、`evidence_support`。

Candidate 值得推進時：

- dev 的目標 slice 有正向 delta。
- holdout 沒有重要 regression。
- RAG 的 `recall_at_5`、`mrr`、`ndcg_at_5` 不退。
- RCA 的 `root_cause_at_1`、`category_accuracy`、`evidence_support` 不退。
- `unsupported_answer_rate` 與 `unsupported_root_cause_rate` 沒有上升。

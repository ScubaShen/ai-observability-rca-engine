# Evaluation Compare Report

- Verdict: `needs_review`
- Advanced RAG acceptance: `failed`
- Acceptance profile: `advanced_rag`

## Overall Metrics

| Metric | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| `rag.recall_at_5` | 0.7778 | 0.8229 | +0.0451 |
| `rag.recall_at_10` | 0.8889 | 0.9097 | +0.0208 |
| `rag.mrr` | 1.0000 | 0.8750 | -0.1250 |
| `rag.ndcg_at_5` | 0.9269 | 0.9234 | -0.0035 |
| `rag.citation_coverage` | 1.0000 | 0.9167 | -0.0833 |
| `rag.unsupported_answer_rate` | 0.0000 | 0.0000 | +0.0000 |
| `rca.root_cause_at_1` | 0.0000 | 0.0000 | +0.0000 |
| `rca.root_cause_at_3` | 1.0000 | 1.0000 | +0.0000 |
| `rca.evidence_support` | 0.5000 | 0.5000 | +0.0000 |
| `rca.unsupported_root_cause_rate` | 0.0000 | 0.0000 | +0.0000 |

## Advanced RAG Acceptance

Focus slices: `semantic_gap`, `noisy_query`, `runbook_discrimination`, `cross_incident`, `evidence_support`

### Improvements

- semantic_gap.rag.ndcg_at_5: 0.8539 -> 0.9234 (+0.0695)
- evidence_support.rag.recall_at_5: 0.0 -> 0.7778 (+0.7778)
- evidence_support.rag.mrr: 0.0 -> 1.0 (+1.0000)
- evidence_support.rag.ndcg_at_5: 0.0 -> 1.0 (+1.0000)

### Regressions

- semantic_gap.rag.recall_at_5: 0.8889 -> 0.8229 (-0.0660)
- semantic_gap.rag.mrr: 1.0 -> 0.875 (-0.1250)

### Guardrails

- overall.rag.citation_coverage: 1.0 -> 0.9167 (-0.0833)

### Missing Slices

- noisy_query
- runbook_discrimination
- cross_incident


## Case-Level Changes

### Regressions

- None

### Improvements

- `rag` `rag_holdout_inventory_change_001`, incident `incident_0316b1fa6798d2c366ac9c1f`: ndcg_at_5_increased
- `rag` `rag_holdout_checkout_chinese_followup_001`: recall_at_5_increased,recall_at_10_increased,recovered_expected_ids


## Metadata

- `baseline`: `runtime/output/eval-holdout-baseline.json`
- `baseline_mode`: `replay`
- `candidate`: `runtime/output/eval-holdout-candidate.json`
- `candidate_mode`: `replay`

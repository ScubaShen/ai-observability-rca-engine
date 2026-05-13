# Evaluation Compare Report

- Verdict: `needs_review`
- Advanced RAG acceptance: `passed`
- Acceptance profile: `advanced_rag`

## Overall Metrics

| Metric | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| `rag.recall_at_5` | 0.6817 | 0.8095 | +0.1278 |
| `rag.recall_at_10` | 0.8913 | 0.9358 | +0.0445 |
| `rag.mrr` | 0.8889 | 0.9167 | +0.0278 |
| `rag.ndcg_at_5` | 0.8382 | 0.9418 | +0.1036 |
| `rag.citation_coverage` | 0.8333 | 0.9445 | +0.1112 |
| `rag.unsupported_answer_rate` | 0.0000 | 0.0000 | +0.0000 |
| `rca.root_cause_at_1` | 0.5000 | 0.5000 | +0.0000 |
| `rca.root_cause_at_3` | 1.0000 | 1.0000 | +0.0000 |
| `rca.evidence_support` | 0.6667 | 0.6667 | +0.0000 |
| `rca.unsupported_root_cause_rate` | 0.0000 | 0.0000 | +0.0000 |

## Advanced RAG Acceptance

Focus slices: `semantic_gap`, `noisy_query`, `runbook_discrimination`, `cross_incident`, `evidence_support`

### Improvements

- semantic_gap.rag.recall_at_5: 0.7577 -> 0.821 (+0.0633)
- semantic_gap.rag.ndcg_at_5: 0.9076 -> 1.0 (+0.0924)
- runbook_discrimination.rag.recall_at_5: 0.5 -> 1.0 (+0.5000)
- runbook_discrimination.rag.mrr: 0.3333 -> 0.5 (+0.1667)
- runbook_discrimination.rag.ndcg_at_5: 0.3066 -> 0.6509 (+0.3443)
- cross_incident.rag.recall_at_5: 0.6125 -> 0.6625 (+0.0500)

### Regressions

- None

### Guardrails

- None

### Missing Slices

- None


## Case-Level Changes

### Regressions

- `rag` `rag_dev_checkout_semantic_long_001`, incident `incident_1b7bcd03f4236106c5bbdf62`: recall_at_5_decreased
- `rag` `rag_dev_multiturn_context_001`: lost_expected_ids
- `rag` `rag_dev_payment_similarity_001`: lost_expected_ids

### Improvements

- `rag` `rag_dev_checkout_chinese_001`, incident `incident_1b7bcd03f4236106c5bbdf62`: recall_at_5_increased,recall_at_10_increased,ndcg_at_5_increased,recovered_expected_ids
- `rag` `rag_dev_multiturn_context_001`: recall_at_5_increased,recovered_expected_ids
- `rag` `rag_dev_payment_similarity_001`: recall_at_5_increased,recall_at_10_increased,recovered_expected_ids
- `rag` `rag_dev_runbook_discrimination_001`, incident `incident_1b7bcd03f4236106c5bbdf62`: recall_at_5_increased,mrr_increased,ndcg_at_5_increased


## Metadata

- `baseline`: `runtime/output/eval-dev-baseline.json`
- `baseline_mode`: `replay`
- `candidate`: `runtime/output/eval-dev-candidate.json`
- `candidate_mode`: `replay`

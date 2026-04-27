# AI Observability RCA Engine

[中文主文檔](README.md)

This project is primarily documented in Chinese. This file is a compact English overview for quick onboarding.

## Overview

AI Observability RCA Engine is a container-oriented service that converts observability telemetry into incident candidates, deterministic RCA results, operator-facing reports, and retrieval-ready artifacts.

It is intended to run inside a broader observability stack rather than replace that stack.

## Main Capabilities

- Normalize Kafka-based logs, metrics, and traces into a shared event model
- Extract high-value events such as log error patterns, metric anomalies, and trace errors
- Correlate signals into incident candidates
- Produce deterministic RCA outputs with evidence, timeline, and ranked hypotheses
- Support operator workflows through runbooks, retrieval, postmortem drafts, and the RCA Console

## Quick Architecture

```text
Kafka telemetry
  -> normalization
  -> high-value event extraction
  -> incident correlation
  -> deterministic RCA
  -> report generation
  -> storage + retrieval indexing
  -> API / RCA Console
```

## How To Run

Build:

```bash
docker compose -f docker-compose-java-observability-platorm.yml build ai-observability-rca-engine
```

Run:

```bash
docker compose -f docker-compose-java-observability-platorm.yml up \
  postgres neo4j ai-observability-rca-engine
```

Verify:

```bash
curl -sS http://localhost:18000/health
curl -sS 'http://localhost:18000/knowledge/search?q=application%20exception'
curl -sS -X POST http://localhost:18000/copilot/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is the most likely root cause?","limit":5,"mode":"auto"}'
```

## Documentation

- [Chinese Main README](README.md)
- [Architecture Notes](docs/architecture.md)
- [Operations Guide](docs/operations.md)

## Known Limitations

- RCA reasoning is deterministic and heuristic-driven
- LLM support is optional and must not be required for core operation
- `runtime/output` is the always-on local artifact layer
- `runtime/postgres` and `runtime/neo4j` should be treated as local runtime state, not source assets

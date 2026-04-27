create extension if not exists vector;

create table if not exists normalized_events (
  event_id text primary key,
  event_type text not null,
  source_topic text not null,
  event_time timestamptz not null,
  service text not null,
  env text not null,
  severity text not null,
  trace_id text,
  span_id text,
  correlation_keys text[] not null default '{}',
  payload jsonb not null,
  received_at timestamptz not null default now()
);

create index if not exists idx_normalized_events_service_time
  on normalized_events (service, env, event_time desc);

create index if not exists idx_normalized_events_type_time
  on normalized_events (event_type, event_time desc);

create table if not exists incident_candidates (
  incident_id text primary key,
  status text not null,
  service text not null,
  env text not null,
  severity text not null,
  window_start timestamptz not null,
  window_end timestamptz not null,
  score double precision not null,
  summary text not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_incident_candidates_service_updated
  on incident_candidates (service, env, updated_at desc);

create table if not exists rca_results (
  incident_id text primary key references incident_candidates (incident_id) on delete cascade,
  service text not null,
  env text not null,
  severity text not null,
  confidence double precision not null,
  summary text not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_rca_results_updated
  on rca_results (updated_at desc);

create table if not exists agent_reports (
  incident_id text primary key,
  service text not null,
  env text not null,
  severity text not null,
  summary text not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_agent_reports_updated
  on agent_reports (updated_at desc);

create table if not exists runbooks (
  runbook_id text primary key,
  title text not null,
  categories text[] not null default '{}',
  keywords text[] not null default '{}',
  steps jsonb not null default '[]'::jsonb,
  payload jsonb not null,
  embedding vector(1536),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_runbooks_categories
  on runbooks using gin (categories);

create table if not exists historical_incidents (
  historical_incident_id text primary key,
  service text not null,
  env text not null,
  summary text not null,
  root_cause text,
  payload jsonb not null,
  embedding vector(1536),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_historical_incidents_service
  on historical_incidents (service, env, updated_at desc);

create table if not exists rag_documents (
  document_id text primary key,
  source_type text not null,
  ref_id text not null,
  incident_id text,
  service text,
  env text,
  severity text,
  title text not null,
  content text not null,
  embedding_model text not null default 'hash-v1',
  embedding vector(1536),
  metadata jsonb not null default '{}'::jsonb,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_rag_documents_incident
  on rag_documents (incident_id, updated_at desc);

create index if not exists idx_rag_documents_source
  on rag_documents (source_type, service, env, updated_at desc);

create index if not exists idx_rag_documents_metadata
  on rag_documents using gin (metadata);

create index if not exists idx_rag_documents_embedding
  on rag_documents using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

create table if not exists rag_query_traces (
  query_id text primary key,
  incident_id text,
  question text not null,
  intent text not null,
  final_answer text not null,
  latency_ms integer not null,
  token_cost double precision not null default 0,
  cache_hit boolean not null default false,
  response_path text not null,
  payload jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_rag_query_traces_created
  on rag_query_traces (created_at desc);

create index if not exists idx_rag_query_traces_incident
  on rag_query_traces (incident_id, created_at desc);

create table if not exists copilot_feedback (
  feedback_id text primary key,
  query_id text,
  incident_id text,
  rating text not null,
  comment text,
  correct_root_cause text,
  correct_runbook_id text,
  payload jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_copilot_feedback_created
  on copilot_feedback (created_at desc);

create table if not exists storage_errors (
  error_id bigserial primary key,
  component text not null,
  operation text not null,
  error text not null,
  created_at timestamptz not null default now()
);

insert into runbooks (runbook_id, title, categories, keywords, steps, payload)
values
  (
    'rb-application-exception',
    'Application exception investigation',
    array['application'],
    array['exception', 'log_error_pattern', 'trace.error'],
    '[
      "Open Loki around the incident window and inspect the exception stack.",
      "Open Tempo for the related trace and locate the failing span.",
      "Compare recent code/deploy/config changes for the service.",
      "If the exception is user-input related, capture request attributes and reproduce safely."
    ]'::jsonb,
    '{
      "runbook_id": "rb-application-exception",
      "title": "Application exception investigation",
      "categories": ["application"],
      "keywords": ["exception", "log_error_pattern", "trace.error"],
      "steps": [
        "Open Loki around the incident window and inspect the exception stack.",
        "Open Tempo for the related trace and locate the failing span.",
        "Compare recent code/deploy/config changes for the service.",
        "If the exception is user-input related, capture request attributes and reproduce safely."
      ]
    }'::jsonb
  ),
  (
    'rb-dependency-latency',
    'Dependency latency or failure investigation',
    array['dependency'],
    array['dependency', 'latency', 'trace.slow_span'],
    '[
      "Identify the dependency target from the slow or failing span.",
      "Check dependency latency, error rate, and saturation dashboards.",
      "Verify network, connection pool, and timeout configuration.",
      "Escalate to the dependency owner if the dependency is external to this service."
    ]'::jsonb,
    '{
      "runbook_id": "rb-dependency-latency",
      "title": "Dependency latency or failure investigation",
      "categories": ["dependency"],
      "keywords": ["dependency", "latency", "trace.slow_span"],
      "steps": [
        "Identify the dependency target from the slow or failing span.",
        "Check dependency latency, error rate, and saturation dashboards.",
        "Verify network, connection pool, and timeout configuration.",
        "Escalate to the dependency owner if the dependency is external to this service."
      ]
    }'::jsonb
  ),
  (
    'rb-resource-load',
    'Resource saturation or load anomaly investigation',
    array['resource_or_load'],
    array['metric', 'anomaly', 'saturation', 'load'],
    '[
      "Compare anomalous metric with request throughput and error rate.",
      "Inspect JVM memory, thread, GC, CPU, and queue depth metrics.",
      "Check whether horizontal scaling or traffic shaping is needed.",
      "Review recent traffic, batch jobs, and deploy changes."
    ]'::jsonb,
    '{
      "runbook_id": "rb-resource-load",
      "title": "Resource saturation or load anomaly investigation",
      "categories": ["resource_or_load"],
      "keywords": ["metric", "anomaly", "saturation", "load"],
      "steps": [
        "Compare anomalous metric with request throughput and error rate.",
        "Inspect JVM memory, thread, GC, CPU, and queue depth metrics.",
        "Check whether horizontal scaling or traffic shaping is needed.",
        "Review recent traffic, batch jobs, and deploy changes."
      ]
    }'::jsonb
  )
on conflict (runbook_id) do nothing;

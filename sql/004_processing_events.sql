-- Ejecutar despues de 003_presence_verification.sql.
-- Historial append-only del procesamiento para auditoria y metricas.

create table if not exists public.processing_events (
  id uuid primary key default gen_random_uuid(),
  evidence_id uuid not null references public.evidences(id) on delete cascade,
  stage text not null check (stage in (
    'received', 'queued', 'visual_ai', 'geospatial', 'decision', 'human_review'
  )),
  status text not null check (status in (
    'pending', 'processing', 'completed', 'inconclusive', 'failed', 'skipped'
  )),
  title text not null,
  detail text not null default '',
  duration_ms integer check (duration_ms is null or duration_ms >= 0),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists processing_events_evidence_created_idx
  on public.processing_events (evidence_id, created_at asc);
create index if not exists processing_events_stage_status_idx
  on public.processing_events (stage, status, created_at desc);

alter table public.processing_events enable row level security;

-- El historial se escribe y consulta mediante FastAPI con service_role.
-- No se habilitan UPDATE ni DELETE desde clientes para conservar trazabilidad.

comment on table public.processing_events is
  'Eventos inmutables y cronologicos del pipeline de validacion.';

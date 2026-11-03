-- Ejecutar despues de 013_evidence_duplicate_statuses.sql.
-- Permite identificar explicitamente la finalizacion del cuestionario.

alter table public.processing_events
  drop constraint if exists processing_events_stage_check;

alter table public.processing_events
  add constraint processing_events_stage_check check (stage in (
    'received',
    'queued',
    'visual_ai',
    'geospatial',
    'decision',
    'human_review',
    'community_profile'
  ));

-- Ejecutar despues de 001_backend_schema.sql.
-- Agrega trazabilidad del Score Multimodal sin eliminar informacion existente.

alter table public.evidences
  add column if not exists gps_accuracy_m double precision,
  add column if not exists capture_source text not null default 'unknown',
  add column if not exists evidence_coverage double precision,
  add column if not exists duplicate_status text;

alter table public.evidences drop constraint if exists evidences_gps_accuracy_check;
alter table public.evidences add constraint evidences_gps_accuracy_check
  check (gps_accuracy_m is null or gps_accuracy_m between 0 and 10000);

alter table public.evidences drop constraint if exists evidences_capture_source_check;
alter table public.evidences add constraint evidences_capture_source_check
  check (capture_source in ('camera', 'gallery', 'unknown'));

alter table public.evidences drop constraint if exists evidences_coverage_check;
alter table public.evidences add constraint evidences_coverage_check
  check (evidence_coverage is null or evidence_coverage between 0 and 1);

alter table public.evidences drop constraint if exists evidences_duplicate_status_check;
alter table public.evidences add constraint evidences_duplicate_status_check
  check (
    duplicate_status is null or duplicate_status in (
      'not_evaluated', 'no_match', 'nearby_match', 'high_match'
    )
  );

alter table public.validation_results
  add column if not exists coverage double precision,
  add column if not exists component_scores jsonb not null default '{}'::jsonb,
  add column if not exists duplicate_result jsonb not null default '{}'::jsonb,
  add column if not exists rule_version text not null default 'legacy';

alter table public.validation_results drop constraint if exists validation_results_coverage_check;
alter table public.validation_results add constraint validation_results_coverage_check
  check (coverage is null or coverage between 0 and 1);

create index if not exists validation_results_rule_version_idx
  on public.validation_results (rule_version, created_at desc);

comment on column public.evidences.evidence_coverage is
  'Proporcion de fuentes ponderadas disponibles; no equivale al score de plausibilidad.';
comment on column public.validation_results.component_scores is
  'Desglose explicable y versionado del Score Multimodal.';

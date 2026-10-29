-- Ejecutar despues de 007_route_visits_passport.sql.
-- Distingue descubrimientos nuevos de evidencia aportada a un lugar existente.

alter table public.evidences
  add column if not exists contribution_type text not null default 'new_place',
  add column if not exists target_place_id bigint,
  add column if not exists target_place_snapshot jsonb not null default '{}'::jsonb,
  add column if not exists target_distance_m double precision;

alter table public.evidences drop constraint if exists evidences_contribution_type_check;
alter table public.evidences add constraint evidences_contribution_type_check
  check (contribution_type in ('new_place', 'existing_place'));

alter table public.evidences drop constraint if exists evidences_target_place_required_check;
alter table public.evidences add constraint evidences_target_place_required_check
  check (
    (contribution_type = 'new_place' and target_place_id is null)
    or
    (contribution_type = 'existing_place' and target_place_id is not null)
  );

alter table public.evidences drop constraint if exists evidences_target_distance_check;
alter table public.evidences add constraint evidences_target_distance_check
  check (target_distance_m is null or target_distance_m >= 0);

create index if not exists evidences_target_place_idx
  on public.evidences (target_place_id, created_at desc)
  where target_place_id is not null;

comment on column public.evidences.contribution_type is
  'new_place para descubrimientos; existing_place para evidencia de un atractivo ya registrado.';
comment on column public.evidences.target_place_id is
  'Identificador del lugar turistico elegido por el usuario. Se valida en FastAPI.';
comment on column public.evidences.target_place_snapshot is
  'Copia auditable del lugar oficial al momento del aporte.';
comment on column public.evidences.target_distance_m is
  'Distancia entre la coordenada de la evidencia y el lugar seleccionado.';

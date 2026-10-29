-- Ejecutar despues de 001_backend_schema.sql y 002_multimodal_scoring.sql.
-- Implementa la ventana movil de presencia GPS. Cada muestra conserva su
-- timestamp original y solo puede respaldar evidencias durante 24 horas.

create table if not exists public.presence_samples (
  id uuid primary key default gen_random_uuid(),
  client_sample_id uuid not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  device_id uuid not null,
  latitude double precision not null check (latitude between -90 and 90),
  longitude double precision not null check (longitude between -180 and 180),
  altitude double precision,
  accuracy_m double precision not null check (accuracy_m between 0 and 10000),
  recorded_at timestamptz not null,
  source text not null default 'app_open' check (
    source in ('app_open', 'app_resume', 'map', 'route', 'capture', 'manual')
  ),
  is_mocked boolean,
  location geography(point, 4326)
    generated always as (
      st_setsrid(st_makepoint(longitude, latitude), 4326)::geography
    ) stored,
  created_at timestamptz not null default now(),
  unique (user_id, client_sample_id)
);

create index if not exists presence_samples_user_recorded_idx
  on public.presence_samples (user_id, recorded_at desc);
create index if not exists presence_samples_location_gix
  on public.presence_samples using gist (location);

alter table public.evidences
  add column if not exists presence_sample_id uuid references public.presence_samples(id) on delete set null,
  add column if not exists presence_status text not null default 'unavailable',
  add column if not exists presence_expires_at timestamptz,
  add column if not exists presence_attestation jsonb not null default '{}'::jsonb;

alter table public.evidences drop constraint if exists evidences_presence_status_check;
alter table public.evidences add constraint evidences_presence_status_check
  check (presence_status in ('confirmed', 'partial', 'not_confirmed', 'unavailable'));

create index if not exists evidences_presence_status_idx
  on public.evidences (presence_status, presence_expires_at);

alter table public.presence_samples enable row level security;

drop policy if exists "users_read_own_presence_samples" on public.presence_samples;
create policy "users_read_own_presence_samples"
on public.presence_samples for select to authenticated
using (auth.uid() = user_id);

-- Las escrituras pasan por FastAPI con service_role para validar timestamps,
-- dispositivo y duplicados. Las muestras vencidas no se usan en decisiones.

comment on table public.presence_samples is
  'Muestras GPS temporales para corroborar presencia; no representan rastreo en tiempo real.';
comment on column public.evidences.presence_attestation is
  'Resumen auditable de presencia. Los puntos GPS crudos tienen retencion corta.';

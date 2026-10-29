-- Ejecutar en Supabase SQL Editor. No elimina ni modifica las tablas actuales.
create extension if not exists pgcrypto;
create extension if not exists postgis;

create table if not exists public.evidences (
  id uuid primary key default gen_random_uuid(),
  client_evidence_id uuid not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 180),
  description text not null default '',
  object_key text not null,
  original_filename text not null,
  mime_type text not null check (mime_type in ('image/jpeg', 'image/png', 'image/webp')),
  content_hash text,
  latitude double precision not null check (latitude between -90 and 90),
  longitude double precision not null check (longitude between -180 and 180),
  altitude double precision,
  location geography(point, 4326)
    generated always as (
      st_setsrid(st_makepoint(longitude, latitude), 4326)::geography
    ) stored,
  captured_at timestamptz,
  status text not null default 'pending' check (
    status in (
      'pending', 'processing_ai', 'processing_gis', 'candidate',
      'needs_review', 'duplicate', 'rejected', 'validated', 'failed'
    )
  ),
  predicted_category text check (
    predicted_category is null or predicted_category in (
      'bosque', 'cascada', 'desierto', 'lago',
      'montana', 'nevado', 'playa', 'volcan'
    )
  ),
  confidence double precision check (confidence is null or confidence between 0 and 1),
  score double precision check (score is null or score between 0 and 1),
  decision_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, client_evidence_id)
);

create index if not exists evidences_user_created_idx
  on public.evidences (user_id, created_at desc);
create index if not exists evidences_status_idx on public.evidences (status);
create index if not exists evidences_location_gix on public.evidences using gist (location);

create table if not exists public.validation_jobs (
  id uuid primary key default gen_random_uuid(),
  evidence_id uuid not null references public.evidences(id) on delete cascade,
  status text not null default 'pending' check (
    status in ('pending', 'processing_ai', 'processing_gis', 'completed', 'failed')
  ),
  attempts integer not null default 0,
  error text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists validation_jobs_evidence_idx
  on public.validation_jobs (evidence_id, created_at desc);

create table if not exists public.validation_results (
  id uuid primary key default gen_random_uuid(),
  evidence_id uuid not null references public.evidences(id) on delete cascade,
  source text not null,
  model_version text not null default 'unknown',
  status text not null,
  category text,
  confidence double precision,
  score double precision,
  reason text,
  geospatial_result jsonb not null default '{}'::jsonb,
  raw_result jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists validation_results_evidence_idx
  on public.validation_results (evidence_id, created_at desc);

create or replace function public.obtener_evidencias_cercanas(
  lat_usuario double precision,
  lng_usuario double precision,
  radio_metros double precision default 10000
)
returns table (
  id uuid,
  nombre text,
  descripcion text,
  latitud double precision,
  longitud double precision,
  categoria_ia text,
  confianza_ia double precision,
  estado_validacion text,
  object_key text
)
language sql
security definer
set search_path = public
stable
as $$
  select
    e.id,
    e.name,
    e.description,
    e.latitude,
    e.longitude,
    e.predicted_category,
    e.confidence,
    e.status,
    e.object_key
  from public.evidences e
  where e.status in ('candidate', 'needs_review', 'validated')
    and st_dwithin(
      e.location,
      st_setsrid(st_makepoint(lng_usuario, lat_usuario), 4326)::geography,
      radio_metros
    )
  order by e.location <-> st_setsrid(st_makepoint(lng_usuario, lat_usuario), 4326)::geography;
$$;

revoke all on function public.obtener_evidencias_cercanas(double precision, double precision, double precision)
  from public;
grant execute on function public.obtener_evidencias_cercanas(double precision, double precision, double precision)
  to service_role;

create table if not exists public.satellite_requests (
  id uuid primary key default gen_random_uuid(),
  evidence_id uuid not null references public.evidences(id) on delete cascade,
  provider text not null check (provider in ('sentinel_2', 'perusat_1')),
  status text not null default 'pending' check (
    status in ('pending', 'requested', 'processing', 'available', 'unavailable', 'failed')
  ),
  requested_at timestamptz not null default now(),
  completed_at timestamptz,
  acquisition_date timestamptz,
  image_object_key text,
  cloud_coverage double precision,
  spatial_resolution_m double precision,
  result jsonb not null default '{}'::jsonb,
  error text
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists evidences_set_updated_at on public.evidences;
create trigger evidences_set_updated_at
before update on public.evidences
for each row execute function public.set_updated_at();

alter table public.evidences enable row level security;
alter table public.validation_jobs enable row level security;
alter table public.validation_results enable row level security;
alter table public.satellite_requests enable row level security;

drop policy if exists "users_read_own_evidences" on public.evidences;
create policy "users_read_own_evidences"
on public.evidences for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "users_insert_own_evidences" on public.evidences;
create policy "users_insert_own_evidences"
on public.evidences for insert to authenticated
with check (auth.uid() = user_id);

-- Jobs, resultados y solicitudes satelitales se escriben exclusivamente desde
-- FastAPI con service_role. El usuario los consulta mediante la API.


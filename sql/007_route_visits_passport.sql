-- Ejecutar despues de 006_fix_nearby_places_rpc.sql.
-- Registra visitas de recorridos y alimenta el Pasaporte RutaAmiga.

create table if not exists public.route_visits (
  id uuid primary key default gen_random_uuid(),
  client_visit_id uuid not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  route_id text not null,
  place_id text not null,
  place_name text not null,
  place_category text not null default '',
  place_region text not null default '',
  place_source text not null check (place_source in ('official', 'community')),
  target_latitude double precision not null check (target_latitude between -90 and 90),
  target_longitude double precision not null check (target_longitude between -180 and 180),
  recorded_latitude double precision not null check (recorded_latitude between -90 and 90),
  recorded_longitude double precision not null check (recorded_longitude between -180 and 180),
  gps_accuracy_m double precision not null check (gps_accuracy_m between 0 and 10000),
  distance_m double precision not null check (distance_m >= 0),
  verification_radius_m double precision not null check (verification_radius_m > 0),
  visit_verified boolean not null default false,
  rating smallint check (rating between 1 and 5),
  comment text not null default '',
  photo_object_key text,
  moderation_status text not null default 'pending' check (
    moderation_status in ('pending', 'approved', 'rejected', 'not_required')
  ),
  captured_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, client_visit_id)
);

create index if not exists route_visits_user_created_idx
  on public.route_visits (user_id, created_at desc);
create index if not exists route_visits_place_idx
  on public.route_visits (place_id, visit_verified, created_at desc);
create index if not exists route_visits_route_idx
  on public.route_visits (user_id, route_id, created_at asc);

alter table public.route_visits enable row level security;

drop policy if exists "users_read_own_route_visits" on public.route_visits;
create policy "users_read_own_route_visits"
on public.route_visits for select to authenticated
using (auth.uid() = user_id);

-- Las escrituras pasan por FastAPI con service_role. El servidor calcula la
-- distancia y decide si la visita puede considerarse verificada.

comment on table public.route_visits is
  'Visitas de recorridos verificadas por proximidad GPS para el Pasaporte RutaAmiga.';
comment on column public.route_visits.visit_verified is
  'Confirma presencia aproximada; no equivale a validar el atractivo turistico.';

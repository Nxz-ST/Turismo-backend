-- Ejecutar despues de 009_user_travel_state.sql.
-- Añade reportes estructurados de condición y acceso a las visitas verificadas.
-- También recupera instalaciones donde 007_route_visits_passport.sql no se
-- ejecutó: crear la tabla con IF NOT EXISTS hace esta migración idempotente.

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

comment on table public.route_visits is
  'Visitas de recorridos verificadas por proximidad GPS para el Pasaporte RutaAmiga.';
comment on column public.route_visits.visit_verified is
  'Confirma presencia aproximada; no equivale a validar el atractivo turistico.';

alter table public.route_visits
  add column if not exists place_condition text,
  add column if not exists access_condition text;

alter table public.route_visits drop constraint if exists route_visits_place_condition_check;
alter table public.route_visits add constraint route_visits_place_condition_check
  check (place_condition is null or place_condition in ('good', 'regular', 'poor'));

alter table public.route_visits drop constraint if exists route_visits_access_condition_check;
alter table public.route_visits add constraint route_visits_access_condition_check
  check (access_condition is null or access_condition in ('open', 'difficult', 'blocked'));

create index if not exists route_visits_verified_place_recent_idx
  on public.route_visits (place_id, captured_at desc)
  where visit_verified = true;

comment on column public.route_visits.place_condition is
  'Condición observada durante una visita GPS: good, regular o poor.';
comment on column public.route_visits.access_condition is
  'Acceso observado durante una visita GPS: open, difficult o blocked.';

-- Permite conservar varias rutas personales, además del viaje que se está editando.
alter table public.user_travel_state
  add column if not exists saved_routes jsonb not null default '[]'::jsonb;

alter table public.user_travel_state drop constraint if exists user_travel_state_saved_routes_array;
alter table public.user_travel_state add constraint user_travel_state_saved_routes_array
  check (jsonb_typeof(saved_routes) = 'array');

comment on column public.user_travel_state.saved_routes is
  'Hasta 50 rutas personales nombradas y sincronizadas por usuario.';

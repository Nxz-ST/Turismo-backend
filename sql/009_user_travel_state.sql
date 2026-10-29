-- Ejecutar despues de 008_existing_place_contributions.sql.
-- Sincroniza favoritos, viaje personalizado y reseñas locales por usuario.

create table if not exists public.user_travel_state (
  user_id uuid primary key references auth.users(id) on delete cascade,
  favorites jsonb not null default '[]'::jsonb,
  trip jsonb not null default '[]'::jsonb,
  reviews jsonb not null default '{}'::jsonb,
  version bigint not null default 1 check (version > 0),
  updated_at timestamptz not null default now(),
  constraint user_travel_state_favorites_array check (jsonb_typeof(favorites) = 'array'),
  constraint user_travel_state_trip_array check (jsonb_typeof(trip) = 'array'),
  constraint user_travel_state_reviews_object check (jsonb_typeof(reviews) = 'object')
);

alter table public.user_travel_state enable row level security;

drop policy if exists "users_read_own_travel_state" on public.user_travel_state;
create policy "users_read_own_travel_state"
on public.user_travel_state for select to authenticated
using (auth.uid() = user_id);

-- Las escrituras pasan por FastAPI con service_role para validar tamaño,
-- estructura y pertenencia antes de persistir el documento.

comment on table public.user_travel_state is
  'Biblioteca sincronizada por usuario: favoritos, ruta personalizada y reseñas.';


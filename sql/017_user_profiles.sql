-- Ejecutar despues de 016_agency_benefits.sql.
-- Perfil de viajero opcional y registro del consentimiento (Ley 29733).
-- Solo datos con finalidad declarada en la Politica de privacidad v1.0:
-- sin fecha de nacimiento exacta, DNI, telefono, direccion ni genero.

create table if not exists public.user_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  traveler_type text check (traveler_type in ('local', 'national', 'foreign')),
  origin_region text check (char_length(origin_region) <= 60),
  origin_country text check (char_length(origin_country) <= 60),
  age_range text check (age_range in ('18-24', '25-34', '35-44', '45-54', '55-64', '65+')),
  interests text[] not null default '{}'::text[],
  hiking_experience text check (hiking_experience in ('beginner', 'intermediate', 'advanced')),
  referral_source text check (referral_source in ('friends', 'social_media', 'university', 'agency', 'search', 'other')),
  terms_version text check (char_length(terms_version) <= 20),
  terms_accepted_at timestamptz,
  research_consent boolean not null default false,
  research_consent_at timestamptz,
  onboarding_completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint user_profiles_interests_allowed check (
    interests <@ array['nature', 'adventure', 'culture', 'beach', 'gastronomy', 'photography', 'relaxation']::text[]
  )
);

alter table public.user_profiles enable row level security;

drop policy if exists "users_read_own_profile" on public.user_profiles;
create policy "users_read_own_profile"
on public.user_profiles for select to authenticated
using (auth.uid() = user_id);

-- Las escrituras pasan por FastAPI con service_role para validar valores
-- permitidos y fechar el consentimiento en el servidor.

comment on table public.user_profiles is
  'Perfil de viajero opcional y consentimiento a Terminos/Privacidad e investigacion.';

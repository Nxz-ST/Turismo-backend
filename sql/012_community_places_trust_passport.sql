-- Ejecutar después de 011_coordinate_quality_audit.sql.
-- Convierte los descubrimientos aprobados en lugares comunitarios canónicos y
-- permite que nuevas evidencias alimenten la misma ficha sin crear duplicados.

create table if not exists public.community_places (
  id uuid primary key default gen_random_uuid(),
  origin_evidence_id uuid not null unique
    references public.evidences(id) on delete restrict,
  name text not null check (char_length(name) between 1 and 180),
  description text not null default '',
  category text not null check (
    category in (
      'bosque', 'cascada', 'desierto', 'lago',
      'montana', 'nevado', 'playa', 'volcan'
    )
  ),
  latitude double precision not null check (latitude between -90 and 90),
  longitude double precision not null check (longitude between -180 and 180),
  altitude double precision,
  location geography(point, 4326)
    generated always as (
      st_setsrid(st_makepoint(longitude, latitude), 4326)::geography
    ) stored,
  primary_photo_object_key text,
  publication_status text not null default 'published' check (
    publication_status in ('published', 'under_review', 'hidden')
  ),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists community_places_location_gix
  on public.community_places using gist (location);
create index if not exists community_places_status_idx
  on public.community_places (publication_status, updated_at desc);

alter table public.community_places enable row level security;

drop trigger if exists community_places_set_updated_at
  on public.community_places;
create trigger community_places_set_updated_at
before update on public.community_places
for each row execute function public.set_updated_at();

alter table public.evidences
  add column if not exists community_place_id uuid
    references public.community_places(id) on delete set null,
  add column if not exists target_community_place_id uuid
    references public.community_places(id) on delete set null;

alter table public.evidences
  drop constraint if exists evidences_target_place_required_check;
alter table public.evidences
  add constraint evidences_target_place_required_check check (
    (
      contribution_type = 'new_place'
      and target_place_id is null
      and target_community_place_id is null
    )
    or
    (
      contribution_type = 'existing_place'
      and (
        (target_place_id is not null and target_community_place_id is null)
        or
        (target_place_id is null and target_community_place_id is not null)
      )
    )
  );

create index if not exists evidences_community_place_idx
  on public.evidences (community_place_id, updated_at desc)
  where community_place_id is not null;
create index if not exists evidences_target_community_place_idx
  on public.evidences (target_community_place_id, updated_at desc)
  where target_community_place_id is not null;

-- Recupera los descubrimientos que ya fueron validados antes de esta mejora.
insert into public.community_places (
  id,
  origin_evidence_id,
  name,
  description,
  category,
  latitude,
  longitude,
  altitude,
  primary_photo_object_key
)
select
  e.id,
  e.id,
  e.name,
  e.description,
  e.predicted_category,
  e.latitude,
  e.longitude,
  e.altitude,
  e.object_key
from public.evidences e
where e.status = 'validated'
  and e.contribution_type = 'new_place'
  and e.predicted_category is not null
on conflict (origin_evidence_id) do nothing;

update public.evidences e
set community_place_id = cp.id
from public.community_places cp
where cp.origin_evidence_id = e.id
  and e.community_place_id is null;

-- Consolida también los duplicados que el panel ya había enlazado mediante el
-- snapshot auditable antes de existir la relación canónica.
update public.evidences e
set
  contribution_type = 'existing_place',
  target_place_id = null,
  target_community_place_id = cp.id,
  community_place_id = cp.id
from public.community_places cp
where e.status = 'duplicate'
  and e.target_place_snapshot ->> 'community_evidence_id' =
    cp.origin_evidence_id::text;

create or replace function public.obtener_lugares_comunitarios_cercanos(
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
  altitud double precision,
  categoria_ia text,
  estado_validacion text,
  object_key text,
  origin_evidence_id uuid,
  created_at timestamptz,
  updated_at timestamptz
)
language sql
security definer
set search_path = public
stable
as $$
  select
    cp.id,
    cp.name,
    cp.description,
    cp.latitude,
    cp.longitude,
    cp.altitude,
    cp.category,
    'validated'::text,
    cp.primary_photo_object_key,
    cp.origin_evidence_id,
    cp.created_at,
    cp.updated_at
  from public.community_places cp
  where cp.publication_status = 'published'
    and st_dwithin(
      cp.location,
      st_setsrid(st_makepoint(lng_usuario, lat_usuario), 4326)::geography,
      radio_metros
    )
  order by cp.location <->
    st_setsrid(st_makepoint(lng_usuario, lat_usuario), 4326)::geography;
$$;

revoke all on function public.obtener_lugares_comunitarios_cercanos(
  double precision, double precision, double precision
) from public;
grant execute on function public.obtener_lugares_comunitarios_cercanos(
  double precision, double precision, double precision
) to service_role;

comment on table public.community_places is
  'Ficha canónica de un descubrimiento comunitario aprobado; no equivale a un registro oficial MINCETUR.';
comment on column public.evidences.community_place_id is
  'Lugar comunitario al que esta evidencia aporta respaldo.';
comment on column public.evidences.target_community_place_id is
  'Lugar comunitario elegido explícitamente como destino del aporte.';

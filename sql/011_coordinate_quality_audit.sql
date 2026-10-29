-- Ejecutar despues de 010_place_condition_reports.sql.
-- Auditoria no destructiva de coordenadas del catalogo turistico.
--
-- Esta migracion NO reemplaza coordenadas por resultados de una busqueda.
-- Primero marca los puntos sospechosos, conserva candidatos y exige una
-- aprobacion administrativa para aplicar una correccion o un punto de acceso.

alter table public.lugares_turisticos
  add column if not exists coordinate_quality text not null default 'reported',
  add column if not exists coordinate_source text not null default 'mincetur_reported',
  add column if not exists coordinate_verified_at timestamptz,
  add column if not exists access_latitud double precision,
  add column if not exists access_longitud double precision,
  add column if not exists access_notes text not null default '',
  add column if not exists access_source text;

alter table public.lugares_turisticos
  drop constraint if exists lugares_turisticos_coordinate_quality_check;
alter table public.lugares_turisticos
  add constraint lugares_turisticos_coordinate_quality_check
  check (coordinate_quality in ('reported', 'verified_correction', 'approximate_cluster'));

alter table public.lugares_turisticos
  drop constraint if exists lugares_turisticos_access_coordinates_check;
alter table public.lugares_turisticos
  add constraint lugares_turisticos_access_coordinates_check
  check (
    (access_latitud is null and access_longitud is null)
    or
    (
      access_latitud between -90 and 90
      and access_longitud between -180 and 180
    )
  );

-- Conserva la trazabilidad de las dos correcciones ya verificadas.
update public.lugares_turisticos
set
  coordinate_quality = 'verified_correction',
  coordinate_source = 'rutaamiga_verified_migration_005',
  coordinate_verified_at = coalesce(coordinate_verified_at, now())
where codigo in (11506, 11531);

-- Marca coincidencias masivas a cuatro decimales como referenciales. No mueve
-- el punto original y nunca rebaja una correccion que ya fue verificada.
with duplicate_clusters as (
  select
    round(latitud::numeric, 4) as lat_key,
    round(longitud::numeric, 4) as lng_key
  from public.lugares_turisticos
  where latitud is not null and longitud is not null
  group by 1, 2
  having count(*) >= 3
)
update public.lugares_turisticos as place
set
  coordinate_quality = 'approximate_cluster',
  coordinate_source = 'rutaamiga_duplicate_cluster_audit'
from duplicate_clusters as cluster
where round(place.latitud::numeric, 4) = cluster.lat_key
  and round(place.longitud::numeric, 4) = cluster.lng_key
  and place.coordinate_quality <> 'verified_correction';

create table if not exists public.place_coordinate_reviews (
  id uuid primary key default gen_random_uuid(),
  audit_key text not null unique,
  place_id bigint not null,
  review_type text not null default 'coordinate' check (
    review_type in ('coordinate', 'access')
  ),
  status text not null default 'flagged' check (
    status in ('flagged', 'candidate', 'applied', 'rejected')
  ),
  flags jsonb not null default '[]'::jsonb check (jsonb_typeof(flags) = 'array'),
  original_latitude double precision not null check (original_latitude between -90 and 90),
  original_longitude double precision not null check (original_longitude between -180 and 180),
  candidate_latitude double precision check (candidate_latitude between -90 and 90),
  candidate_longitude double precision check (candidate_longitude between -180 and 180),
  candidate_name text,
  candidate_address text,
  candidate_source text,
  candidate_reference text,
  candidate_payload jsonb not null default '{}'::jsonb,
  candidate_distance_m double precision check (
    candidate_distance_m is null or candidate_distance_m >= 0
  ),
  confidence double precision check (confidence is null or confidence between 0 and 1),
  reviewed_by uuid references auth.users(id) on delete set null,
  review_note text not null default '',
  reviewed_at timestamptz,
  applied_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint place_coordinate_reviews_candidate_pair_check check (
    (candidate_latitude is null and candidate_longitude is null)
    or
    (candidate_latitude is not null and candidate_longitude is not null)
  )
);

create index if not exists place_coordinate_reviews_status_idx
  on public.place_coordinate_reviews (status, created_at desc);
create index if not exists place_coordinate_reviews_place_idx
  on public.place_coordinate_reviews (place_id, created_at desc);

-- Crea una cola inicial para todos los puntos repetidos detectados. ON
-- CONFLICT conserva decisiones anteriores si se vuelve a ejecutar el script.
insert into public.place_coordinate_reviews (
  audit_key,
  place_id,
  review_type,
  status,
  flags,
  original_latitude,
  original_longitude
)
select
  'duplicate_cluster:' || place.id::text,
  place.id,
  'coordinate',
  'flagged',
  jsonb_build_array('duplicate_coordinate_cluster'),
  place.latitud,
  place.longitud
from public.lugares_turisticos as place
where place.coordinate_quality = 'approximate_cluster'
on conflict (audit_key) do nothing;

alter table public.place_coordinate_reviews enable row level security;

-- No se crean politicas de escritura para clientes. Todas las lecturas y
-- decisiones pasan por FastAPI con service_role y rol de administrador.

drop trigger if exists place_coordinate_reviews_set_updated_at
  on public.place_coordinate_reviews;
create trigger place_coordinate_reviews_set_updated_at
before update on public.place_coordinate_reviews
for each row execute function public.set_updated_at();

create or replace function public.apply_place_coordinate_review(
  p_review_id uuid,
  p_reviewer_id uuid,
  p_note text default ''
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  review_record public.place_coordinate_reviews%rowtype;
begin
  select * into review_record
  from public.place_coordinate_reviews
  where id = p_review_id
  for update;

  if not found then
    raise exception 'Revision de coordenadas no encontrada';
  end if;
  if review_record.status not in ('flagged', 'candidate') then
    raise exception 'La revision ya fue cerrada';
  end if;
  if review_record.candidate_latitude is null
     or review_record.candidate_longitude is null then
    raise exception 'La revision no tiene un candidato completo';
  end if;

  if review_record.review_type = 'coordinate' then
    update public.lugares_turisticos
    set
      latitud = review_record.candidate_latitude,
      longitud = review_record.candidate_longitude,
      ubicacion = st_setsrid(
        st_makepoint(
          review_record.candidate_longitude,
          review_record.candidate_latitude
        ),
        4326
      )::geography,
      coordinate_quality = 'verified_correction',
      coordinate_source = coalesce(
        nullif(review_record.candidate_source, ''),
        'manual_admin_review'
      ),
      coordinate_verified_at = now()
    where id = review_record.place_id;
  else
    update public.lugares_turisticos
    set
      access_latitud = review_record.candidate_latitude,
      access_longitud = review_record.candidate_longitude,
      access_notes = coalesce(nullif(p_note, ''), access_notes),
      access_source = coalesce(
        nullif(review_record.candidate_source, ''),
        'manual_admin_review'
      )
    where id = review_record.place_id;
  end if;

  if not found then
    raise exception 'Lugar turistico no encontrado';
  end if;

  update public.place_coordinate_reviews
  set
    status = 'applied',
    reviewed_by = p_reviewer_id,
    review_note = coalesce(p_note, ''),
    reviewed_at = now(),
    applied_at = now()
  where id = p_review_id;

  return jsonb_build_object(
    'id', p_review_id,
    'place_id', review_record.place_id,
    'review_type', review_record.review_type,
    'status', 'applied'
  );
end;
$$;

revoke all on function public.apply_place_coordinate_review(uuid, uuid, text)
  from public;
grant execute on function public.apply_place_coordinate_review(uuid, uuid, text)
  to service_role;

comment on table public.place_coordinate_reviews is
  'Cola auditable de candidatos de coordenadas y accesos; nunca aplica resultados automaticamente.';
comment on column public.lugares_turisticos.access_latitud is
  'Punto de acceso aprobado para navegacion, distinto de la ubicacion fisica del atractivo.';
comment on column public.lugares_turisticos.coordinate_quality is
  'reported, verified_correction o approximate_cluster.';

-- Solicita a PostgREST refrescar columnas y RPC nuevas al terminar.
notify pgrst, 'reload schema';

-- Ejecutar despues de 005_official_coordinate_corrections.sql.
-- Corrige la RPC heredada: `$3` evita la ambigüedad entre el parámetro
-- radio_metros y la columna lugares_turisticos.radio_metros.

drop function if exists public.obtener_lugares_cercanos(
  double precision,
  double precision,
  double precision
);

create function public.obtener_lugares_cercanos(
  lat_usuario double precision,
  lng_usuario double precision,
  radio_metros double precision default 30000
)
returns setof public.lugares_turisticos
language sql
stable
security invoker
set search_path = public
as $$
  select lugar.*
  from public.lugares_turisticos as lugar
  where lugar.ubicacion is not null
    and st_dwithin(
      lugar.ubicacion,
      st_setsrid(st_makepoint($2, $1), 4326)::geography,
      $3
    )
  order by st_distance(
    lugar.ubicacion,
    st_setsrid(st_makepoint($2, $1), 4326)::geography
  )
  limit 250;
$$;

grant execute on function public.obtener_lugares_cercanos(
  double precision,
  double precision,
  double precision
) to authenticated, service_role;

-- Ejecutar despues de 004_processing_events.sql.
-- Corrige dos registros MINCETUR cuyo punto importado correspondia al centro
-- urbano de Huaraz y cuya altitud tampoco correspondia al nevado.

update public.lugares_turisticos
set
  latitud = -9.439077,
  longitud = -77.302956,
  altitud = 5721,
  ubicacion = st_setsrid(st_makepoint(-77.302956, -9.439077), 4326)::geography
where codigo = 11506;

update public.lugares_turisticos
set
  latitud = -9.525,
  longitud = -77.385,
  altitud = 5434,
  ubicacion = st_setsrid(st_makepoint(-77.385, -9.525), 4326)::geography
where codigo = 11531;

comment on table public.lugares_turisticos is
  'Catalogo turistico oficial. Las correcciones de coordenadas deben conservar fuente y trazabilidad en migraciones.';

-- Ejecutar despues de 012_community_places_trust_passport.sql.
-- Sincroniza la restriccion con todos los estados emitidos por el flujo actual.

alter table public.evidences
  drop constraint if exists evidences_duplicate_status_check;

alter table public.evidences
  add constraint evidences_duplicate_status_check check (
    duplicate_status is null or duplicate_status in (
      'not_evaluated',
      'no_match',
      'nearby_match',
      'high_match',
      'category_conflict',
      'linked_target'
    )
  );

-- Los errores internos historicos no deben formar parte de la explicacion publica.
update public.evidences
set decision_reason =
  'No pudimos completar el análisis automático. Tu aporte está seguro y quedó disponible para reintento o revisión.'
where decision_reason ilike '%supabase respondio%'
   or decision_reason ilike '%supabase respondió%'
   or decision_reason ilike '%failing row%'
   or decision_reason ilike '%sqlstate%';

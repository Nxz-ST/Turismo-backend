-- Reportes ciudadanos estructurados sobre cambios, riesgos y errores de ficha.
create table if not exists public.place_issue_reports (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  place_source text not null check (place_source in ('official', 'community')),
  place_id text not null,
  place_name text not null default '',
  issue_type text not null check (
    issue_type in ('access_closed', 'safety_risk', 'wrong_location', 'outdated_info')
  ),
  details text not null default '' check (char_length(details) <= 500),
  status text not null default 'pending' check (
    status in ('pending', 'reviewed', 'resolved', 'dismissed')
  ),
  observed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz,
  reviewed_by uuid references auth.users(id),
  review_note text not null default ''
);

create index if not exists place_issue_reports_place_idx
  on public.place_issue_reports (place_source, place_id, created_at desc);
create index if not exists place_issue_reports_status_idx
  on public.place_issue_reports (status, created_at desc);
create index if not exists place_issue_reports_user_idx
  on public.place_issue_reports (user_id, created_at desc);

alter table public.place_issue_reports enable row level security;

drop policy if exists "users_read_own_place_issue_reports" on public.place_issue_reports;
create policy "users_read_own_place_issue_reports"
on public.place_issue_reports for select to authenticated
using (auth.uid() = user_id);

comment on table public.place_issue_reports is
  'Alertas ciudadanas pendientes de revisión; no modifican automáticamente una ficha turística.';

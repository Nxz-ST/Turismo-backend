-- Bloqueo de cuentas por contenido prohibido o incumplimiento de los Términos.
-- Una fila = cuenta bloqueada. suspended_until nulo = bloqueo definitivo.
-- Desbloquear = borrar la fila (la decisión queda en suspension_events).

create table if not exists public.account_suspensions (
  user_id uuid primary key references auth.users (id) on delete cascade,
  reason text not null check (char_length(reason) between 3 and 300),
  suspended_until timestamptz,
  suspended_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.suspension_events (
  id bigint generated always as identity primary key,
  user_id uuid not null,
  action text not null check (action in ('suspend', 'lift')),
  reason text,
  suspended_until timestamptz,
  actor_id uuid,
  created_at timestamptz not null default now()
);

alter table public.account_suspensions enable row level security;
alter table public.suspension_events enable row level security;

drop policy if exists "users_read_own_suspension" on public.account_suspensions;
create policy "users_read_own_suspension"
on public.account_suspensions for select to authenticated
using (auth.uid() = user_id);

-- Escrituras y bitácora solo por FastAPI con service_role.

comment on table public.account_suspensions is
  'Cuentas bloqueadas por moderación (Términos y condiciones, sección 4).';
comment on table public.suspension_events is
  'Bitácora de bloqueos y desbloqueos de cuentas.';

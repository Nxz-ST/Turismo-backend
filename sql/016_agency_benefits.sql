create table if not exists public.agencies (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  initials text not null,
  whatsapp_phone text,
  status text not null default 'active' check (status in ('active', 'inactive')),
  is_demo boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.agency_members (
  id uuid primary key default gen_random_uuid(),
  agency_id uuid not null references public.agencies(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  member_role text not null default 'staff' check (member_role in ('owner', 'staff')),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (agency_id, user_id)
);

create table if not exists public.tourism_benefits (
  id uuid primary key default gen_random_uuid(),
  agency_id uuid not null references public.agencies(id) on delete cascade,
  title_template text not null,
  summary_template text not null,
  benefit_label text not null,
  original_price numeric(10,2) not null check (original_price >= 0),
  rutaamiga_price numeric(10,2) not null check (rutaamiga_price >= 0),
  duration text not null,
  included jsonb not null default '[]'::jsonb,
  conditions jsonb not null default '[]'::jsonb,
  rating numeric(2,1) not null default 4.5,
  recommended boolean not null default false,
  applies_to_all boolean not null default true,
  place_source text check (place_source in ('official', 'community')),
  place_id text,
  status text not null default 'active' check (status in ('active', 'inactive')),
  is_demo boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.benefit_redemptions (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  benefit_id uuid not null references public.tourism_benefits(id),
  agency_id uuid not null references public.agencies(id),
  user_id uuid not null references auth.users(id),
  place_source text not null check (place_source in ('official', 'community')),
  place_id text not null,
  place_name text not null,
  status text not null default 'requested' check (status in ('requested', 'confirmed', 'redeemed', 'cancelled', 'expired')),
  expires_at timestamptz not null,
  confirmed_at timestamptz,
  redeemed_at timestamptz,
  cancelled_at timestamptz,
  agency_note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists benefit_redemptions_one_active
  on public.benefit_redemptions(user_id, benefit_id, place_source, place_id)
  where status in ('requested', 'confirmed');
create index if not exists benefit_redemptions_agency_status
  on public.benefit_redemptions(agency_id, status, created_at desc);

create table if not exists public.benefit_audit_events (
  id uuid primary key default gen_random_uuid(),
  redemption_id uuid not null references public.benefit_redemptions(id) on delete cascade,
  actor_user_id uuid references auth.users(id),
  from_status text,
  to_status text not null,
  note text,
  created_at timestamptz not null default now()
);

alter table public.agencies enable row level security;
alter table public.agency_members enable row level security;
alter table public.tourism_benefits enable row level security;
alter table public.benefit_redemptions enable row level security;
alter table public.benefit_audit_events enable row level security;

insert into public.agencies (name, slug, initials, whatsapp_phone, is_demo)
values
  ('Andes Conecta', 'andes-conecta', 'AC', null, true),
  ('Explora Perú', 'explora-peru', 'EP', null, true),
  ('Rutas del Sol', 'rutas-del-sol', 'RS', null, true)
on conflict (slug) do update set name = excluded.name, initials = excluded.initials;

insert into public.tourism_benefits (
  agency_id, title_template, summary_template, benefit_label, original_price,
  rutaamiga_price, duration, included, conditions, rating, recommended, is_demo
)
select a.id, v.title_template, v.summary_template, v.benefit_label, v.original_price,
       v.rutaamiga_price, v.duration, v.included::jsonb, v.conditions::jsonb,
       v.rating, v.recommended, true
from public.agencies a
join (values
  ('andes-conecta', 'Visita {place}', 'Salida de día completo con acompañamiento local y horarios coordinados.', '10% de descuento', 150.00, 135.00, 'Día completo', '["Movilidad de ida y retorno","Acompañamiento de guía local","Coordinación por WhatsApp"]', '["Sujeto a disponibilidad","Presentar el código antes de confirmar","No acumulable con otras promociones"]', 4.8, true),
  ('explora-peru', 'Escapada a {place}', 'Experiencia flexible para conocer el destino con asistencia de un operador local.', '15% de descuento', 120.00, 102.00, 'Medio día', '["Traslado desde punto coordinado","Orientación local","Asistencia por WhatsApp"]', '["Reserva previa requerida","Precio demostrativo por persona","Cupos limitados"]', 4.6, false),
  ('rutas-del-sol', 'Ruta compartida a {place}', 'Alternativa económica para viajar en grupo y coordinar el recorrido.', 'S/ 12 de ahorro', 92.00, 80.00, '6 horas', '["Movilidad compartida","Paradas fotográficas","Coordinación de retorno"]', '["Mínimo de participantes","No incluye alimentación","Confirmación de la agencia requerida"]', 4.5, false)
) as v(slug, title_template, summary_template, benefit_label, original_price, rutaamiga_price, duration, included, conditions, rating, recommended)
  on a.slug = v.slug
where not exists (
  select 1 from public.tourism_benefits b where b.agency_id = a.id and b.title_template = v.title_template
);

comment on table public.benefit_redemptions is
  'Pases de beneficio centralizados. Los datos demo se identifican por la oferta y agencia is_demo.';

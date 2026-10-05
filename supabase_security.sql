-- Eenmalig uitvoeren in Supabase -> SQL Editor.
-- Server-side login-lockout; RLS blijft ingeschakeld en de Streamlit sb_secret_-key beheert deze tabel.
create table if not exists public.login_lockouts (
    "LockoutID" text primary key,
    "Pogingen" integer not null default 0,
    "VergrendeldTot" timestamptz,
    "Bijgewerkt" timestamptz not null default now()
);
alter table public.login_lockouts enable row level security;
create index if not exists login_lockouts_bijgewerkt_idx on public.login_lockouts ("Bijgewerkt");

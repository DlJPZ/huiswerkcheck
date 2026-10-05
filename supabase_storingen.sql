-- Eenmalig uitvoeren in Supabase -> SQL Editor.
-- De app gebruikt een sb_secret_ key op de Streamlit-server; daarom zijn geen publieke RLS-policies nodig.

create table if not exists public.storingen (
    "StoringID" text primary key,
    "Aangemaakt" timestamptz not null default now(),
    "Status" text not null default 'in behandeling'
        check ("Status" in ('in behandeling', 'opgelost')),
    "Titel" text not null,
    "Omschrijving" text not null,
    "Categorie" text not null default 'Overig',
    "Gebruikersnaam" text,
    "Voornaam" text,
    "Cluster" text,
    "BijlagePad" text,
    "AdminNotitie" text not null default '',
    "OpgelostOp" timestamptz
);

alter table public.storingen enable row level security;

create index if not exists storingen_status_aangemaakt_idx
    on public.storingen ("Status", "Aangemaakt" desc);

-- Privé bucket: alleen de server-side secret key kan de bijlagen benaderen.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'storingsbijlagen',
    'storingsbijlagen',
    false,
    8388608,
    array['image/png', 'image/jpeg', 'image/webp', 'application/pdf']
)
on conflict (id) do update set
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

-- Eenmalig uitvoeren in Supabase -> SQL Editor.
-- De app gebruikt een sb_secret_ key op de Streamlit-server; publieke policies zijn niet nodig.

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
    "OpgelostOp" timestamptz,
    "MeldingenAantal" integer not null default 1,
    "ZichtbaarVoorLeerlingen" boolean not null default true
);

alter table public.storingen add column if not exists "MeldingenAantal" integer not null default 1;
alter table public.storingen add column if not exists "ZichtbaarVoorLeerlingen" boolean not null default true;
alter table public.storingen enable row level security;

create index if not exists storingen_status_aangemaakt_idx
    on public.storingen ("Status", "Aangemaakt" desc);

create table if not exists public.storing_bevestigingen (
    "StoringID" text not null references public.storingen("StoringID") on delete cascade,
    "MelderKey" text not null,
    "Aangemaakt" timestamptz not null default now(),
    "IsOorspronkelijkeMelder" boolean not null default false,
    primary key ("StoringID", "MelderKey")
);
alter table public.storing_bevestigingen add column if not exists "IsOorspronkelijkeMelder" boolean not null default false;
alter table public.storing_bevestigingen enable row level security;

create or replace function public.update_storing_meldingen_aantal()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    if tg_op = 'INSERT' then
        if not new."IsOorspronkelijkeMelder" then
            update public.storingen
            set "MeldingenAantal" = "MeldingenAantal" + 1
            where "StoringID" = new."StoringID";
        end if;
        return new;
    elsif tg_op = 'DELETE' then
        if not old."IsOorspronkelijkeMelder" then
            update public.storingen
            set "MeldingenAantal" = greatest(1, "MeldingenAantal" - 1)
            where "StoringID" = old."StoringID";
        end if;
        return old;
    end if;
    return null;
end;
$$;

drop trigger if exists storing_bevestiging_teller on public.storing_bevestigingen;
create trigger storing_bevestiging_teller
after insert or delete on public.storing_bevestigingen
for each row execute function public.update_storing_meldingen_aantal();

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

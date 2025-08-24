create table public.leagues (
    id uuid not null default gen_random_uuid (),
    created_at timestamp with time zone not null default (now() AT TIME ZONE 'utc' :: text),
    updated_at timestamp with time zone null,
    league_id smallint not null,
    update_matches boolean not null default true,
    season smallint not null,
    name text not null,
    constraint leagues_pkey primary key (id)
) TABLESPACE pg_default;

create trigger handle_updated_at BEFORE
update
    on leagues for EACH row execute FUNCTION extensions.moddatetime ('updated_at');
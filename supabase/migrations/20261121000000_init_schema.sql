-- Threads Analyzer: initial schema + RLS
-- Tables: profiles, jobs, posts, job_summaries
--
-- Access model
--   * anon (not logged in): no access to any table.
--   * authenticated: profiles -> read own; jobs -> create/read/delete own;
--     posts / job_summaries -> read only, resolved through jobs.user_id.
--   * Writes to posts / job_summaries / jobs.status etc. are done by the local
--     scraper using the service_role key (bypasses RLS). Never ship that key
--     to the frontend.

-- ---------------------------------------------------------------------------
-- Types
-- ---------------------------------------------------------------------------
create type public.job_status as enum (
  'pending', 'scraping', 'analyzing', 'done', 'failed'
);

-- ---------------------------------------------------------------------------
-- profiles (1:1 with auth.users)
-- ---------------------------------------------------------------------------
create table public.profiles (
  id         uuid primary key references auth.users (id) on delete cascade,
  email      text,
  created_at timestamptz not null default now()
);

-- Auto-create a profile row when a user signs up.
create function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

revoke execute on function public.handle_new_user() from public, anon, authenticated;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- jobs
-- ---------------------------------------------------------------------------
create table public.jobs (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid()
                references auth.users (id) on delete cascade,
  username    text not null
                check (username ~ '^[a-z0-9._]{1,30}$'),  -- normalized, no '@'
  status      public.job_status not null default 'pending',
  post_count  integer not null default 0 check (post_count >= 0),
  error       text,
  created_at  timestamptz not null default now(),
  finished_at timestamptz
);

create index jobs_user_id_created_at_idx
  on public.jobs (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- posts
-- ---------------------------------------------------------------------------
create table public.posts (
  id             uuid primary key default gen_random_uuid(),
  job_id         uuid not null references public.jobs (id) on delete cascade,
  post_url       text not null,
  posted_at      timestamptz,
  text           text,
  views          integer,                       -- nullable: not obtainable logged-out
  views_rounded  boolean not null default false,
  likes          integer not null default 0,
  replies        integer not null default 0,
  reposts        integer not null default 0,
  quotes         integer not null default 0,
  char_count     integer not null default 0,
  hashtag_count  integer not null default 0,
  mention_count  integer not null default 0,
  url_count      integer not null default 0,
  post_type      text,
  "group"        text,
  source         text not null check (source in ('real', 'mock')),
  unique (job_id, post_url)
);

create index posts_job_id_posted_at_idx
  on public.posts (job_id, posted_at desc);

-- ---------------------------------------------------------------------------
-- job_summaries
-- ---------------------------------------------------------------------------
create table public.job_summaries (
  job_id         uuid primary key references public.jobs (id) on delete cascade,
  metrics        jsonb not null default '{}'::jsonb,
  top_posts      jsonb not null default '[]'::jsonb,
  group_analysis jsonb not null default '{}'::jsonb,
  insights       jsonb not null default '[]'::jsonb,
  llm_advice     text,
  updated_at     timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Privileges (defense in depth on top of RLS)
-- ---------------------------------------------------------------------------
revoke all on public.profiles, public.jobs, public.posts, public.job_summaries
  from anon, authenticated;

grant select                 on public.profiles      to authenticated;
grant select, insert, delete on public.jobs          to authenticated;
grant select                 on public.posts         to authenticated;
grant select                 on public.job_summaries to authenticated;

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
alter table public.profiles      enable row level security;
alter table public.jobs          enable row level security;
alter table public.posts         enable row level security;
alter table public.job_summaries enable row level security;

-- profiles: read own row
create policy "profiles_select_own" on public.profiles
  for select to authenticated
  using (id = (select auth.uid()));

-- jobs: create / read / delete own
create policy "jobs_select_own" on public.jobs
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy "jobs_insert_own" on public.jobs
  for insert to authenticated
  with check (user_id = (select auth.uid()));

create policy "jobs_delete_own" on public.jobs
  for delete to authenticated
  using (user_id = (select auth.uid()));

-- posts: read only, via the owning job
create policy "posts_select_via_job" on public.posts
  for select to authenticated
  using (
    exists (
      select 1 from public.jobs j
      where j.id = posts.job_id
        and j.user_id = (select auth.uid())
    )
  );

-- job_summaries: read only, via the owning job
create policy "job_summaries_select_via_job" on public.job_summaries
  for select to authenticated
  using (
    exists (
      select 1 from public.jobs j
      where j.id = job_summaries.job_id
        and j.user_id = (select auth.uid())
    )
  );

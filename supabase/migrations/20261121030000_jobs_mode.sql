-- Login mode: a job is scraped either anonymously (logged out) or with the owner's own Threads session
-- (python -m src.pipeline.run --login). Existing jobs stay 'anonymous'. RLS and grants are unchanged:
-- table-level privileges already cover the new column, and users may still only insert/read/delete their own jobs.

alter table public.jobs
  add column mode text not null default 'anonymous'
  check (mode in ('anonymous', 'login'));

-- T13: let a user re-run their own finished/failed job by setting it back to 'pending'
-- (the local CLI picks pending jobs up). Nothing else on jobs is updatable by users.

grant update (status, error, finished_at) on public.jobs to authenticated;

create policy "jobs_rerun_own" on public.jobs
  for update to authenticated
  using (user_id = (select auth.uid()) and status in ('done', 'failed'))   -- the existing row
  with check (user_id = (select auth.uid()) and status = 'pending');        -- the new row

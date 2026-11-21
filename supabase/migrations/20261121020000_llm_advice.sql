-- T12: the report page stores the LLM advice text. Users may update ONLY job_summaries.llm_advice, and only on their own jobs.

grant update (llm_advice) on public.job_summaries to authenticated;

create policy "job_summaries_update_advice_own" on public.job_summaries
  for update to authenticated
  using (exists (select 1 from public.jobs j where j.id = job_summaries.job_id and j.user_id = (select auth.uid())))
  with check (exists (select 1 from public.jobs j where j.id = job_summaries.job_id and j.user_id = (select auth.uid())));

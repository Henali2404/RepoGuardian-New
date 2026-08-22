-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- Profiles table
create table public.profiles (
  id uuid references auth.users(id) on delete cascade primary key,
  email text not null,
  display_name text,
  github_username text,
  created_at timestamptz default now()
);

-- Auto-create profile when user signs up
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, email, display_name)
  values (new.id, new.email, split_part(new.email, '@', 1));
  return new;
end;
$$ language plpgsql security definer;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- Analysis Jobs
create table public.analysis_jobs (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references public.profiles(id) on delete set null,
  repo_url text not null,
  repo_name text,
  framework text,
  status text not null default 'running',
  error_message text,
  health_score int,
  scores jsonb,
  security_report jsonb,
  market_report jsonb,
  screenshot_b64 text,
  analysis_result jsonb,
  trace_logs jsonb,
  approval_status text default 'pending',
  push_status text default 'not_pushed',
  pr_url text,
  created_at timestamptz default now(),
  completed_at timestamptz
);

-- Additive migration for databases created before complete analysis snapshots.
alter table public.analysis_jobs add column if not exists scores jsonb;
alter table public.analysis_jobs add column if not exists security_report jsonb;
alter table public.analysis_jobs add column if not exists market_report jsonb;
alter table public.analysis_jobs add column if not exists screenshot_b64 text;
alter table public.analysis_jobs add column if not exists analysis_result jsonb;
alter table public.analysis_jobs add column if not exists trace_logs jsonb;
alter table public.analysis_jobs add column if not exists approval_status text default 'pending';
alter table public.analysis_jobs add column if not exists push_status text default 'not_pushed';
alter table public.analysis_jobs add column if not exists pr_url text;

-- Bug Reports
create table public.bug_reports (
  id uuid primary key default uuid_generate_v4(),
  job_id uuid references public.analysis_jobs(id) on delete cascade not null,
  file_path text,
  line_number int,
  error_type text,
  error_description text,
  code_snippet text,
  suggested_fix text,
  severity text,
  created_at timestamptz default now()
);

-- Architecture Issues
create table public.architecture_issues (
  id uuid primary key default uuid_generate_v4(),
  job_id uuid references public.analysis_jobs(id) on delete cascade not null,
  issue_type text,
  severity text,
  title text,
  description text,
  suggestion text,
  file_path text,
  line_number int,
  created_at timestamptz default now()
);

-- AI Analyses
create table public.ai_analyses (
  id uuid primary key default uuid_generate_v4(),
  job_id uuid references public.analysis_jobs(id) on delete cascade not null,
  markdown_report text,
  critical_count int default 0,
  warning_count int default 0,
  info_count int default 0,
  created_at timestamptz default now()
);

-- Security report artifacts
create table public.security_reports (
  id uuid primary key default uuid_generate_v4(),
  job_id uuid references public.analysis_jobs(id) on delete cascade not null,
  report jsonb not null,
  created_at timestamptz default now()
);

-- Generated fixes are stored independently so historical analyses can restore them
-- even when the complete result snapshot was created by an older backend.
create table public.analysis_diffs (
  id uuid primary key default uuid_generate_v4(),
  job_id uuid references public.analysis_jobs(id) on delete cascade not null,
  diff jsonb not null,
  created_at timestamptz default now()
);

create index idx_analysis_diffs_job_id on public.analysis_diffs(job_id);

-- PR History
create table public.pr_history (
  id uuid primary key default uuid_generate_v4(),
  job_id uuid references public.analysis_jobs(id) on delete cascade not null,
  user_id uuid references public.profiles(id) on delete set null,
  repo_url text not null,
  pr_url text not null,
  pr_title text,
  branch_name text,
  files_changed text[],
  bugs_fixed int default 0,
  created_at timestamptz default now()
);

-- Indexes
create index idx_jobs_user_id on public.analysis_jobs(user_id);
create index idx_jobs_status on public.analysis_jobs(status);
create index idx_bug_reports_job_id on public.bug_reports(job_id);
create index idx_arch_issues_job_id on public.architecture_issues(job_id);
create index idx_security_reports_job_id on public.security_reports(job_id);
create index idx_pr_history_user_id on public.pr_history(user_id);
create index idx_pr_history_job_id on public.pr_history(job_id);

-- Optional report tables must also cascade when an analysis is deleted.
-- Apply equivalent ON DELETE CASCADE constraints to any separately-created
-- security/report tables that reference analysis_jobs.

create extension if not exists pgcrypto;

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  display_name text,
  avatar_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.projects (
  id uuid primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  source_url text not null,
  title text,
  status text not null default 'queued'
    check (status in ('queued', 'downloading', 'transcribing', 'analyzing', 'rendering', 'complete', 'failed')),
  progress integer not null default 0 check (progress between 0 and 100),
  message text not null default 'Waiting to start',
  error text,
  clip_count integer not null check (clip_count between 1 and 8),
  target_duration integer not null check (target_duration between 15 and 180),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.project_clips (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  filename text not null,
  title text not null,
  reason text not null,
  start_time double precision not null,
  end_time double precision not null,
  version integer not null default 0,
  edit_settings jsonb,
  social_post text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (project_id, filename)
);

create table public.user_api_keys (
  user_id uuid primary key references auth.users(id) on delete cascade,
  encrypted_key text not null,
  nonce text not null,
  key_last4 text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.analytics_events (
  id bigint generated always as identity primary key,
  user_id uuid references auth.users(id) on delete set null,
  event_name text not null,
  properties jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index projects_user_created_idx on public.projects(user_id, created_at desc);
create index project_clips_project_idx on public.project_clips(project_id);
create index project_clips_user_idx on public.project_clips(user_id);
create index analytics_events_name_created_idx on public.analytics_events(event_name, created_at desc);
create index analytics_events_user_idx on public.analytics_events(user_id);

alter table public.profiles enable row level security;
alter table public.projects enable row level security;
alter table public.project_clips enable row level security;
alter table public.user_api_keys enable row level security;
alter table public.analytics_events enable row level security;

create policy "profiles_select_own" on public.profiles
  for select using ((select auth.uid()) = id);
create policy "profiles_update_own" on public.profiles
  for update using ((select auth.uid()) = id) with check ((select auth.uid()) = id);

create policy "projects_select_own" on public.projects
  for select using ((select auth.uid()) = user_id);
create policy "projects_insert_own" on public.projects
  for insert with check ((select auth.uid()) = user_id);
create policy "projects_update_own" on public.projects
  for update using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "projects_delete_own" on public.projects
  for delete using ((select auth.uid()) = user_id);

create policy "clips_select_own" on public.project_clips
  for select using ((select auth.uid()) = user_id);
create policy "clips_insert_own" on public.project_clips
  for insert with check ((select auth.uid()) = user_id);
create policy "clips_update_own" on public.project_clips
  for update using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "clips_delete_own" on public.project_clips
  for delete using ((select auth.uid()) = user_id);

create policy "keys_select_own" on public.user_api_keys
  for select using ((select auth.uid()) = user_id);
create policy "keys_insert_own" on public.user_api_keys
  for insert with check ((select auth.uid()) = user_id);
create policy "keys_update_own" on public.user_api_keys
  for update using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "keys_delete_own" on public.user_api_keys
  for delete using ((select auth.uid()) = user_id);

create policy "events_insert_own" on public.analytics_events
  for insert with check ((select auth.uid()) = user_id);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger profiles_set_updated_at before update on public.profiles
  for each row execute function public.set_updated_at();
create trigger projects_set_updated_at before update on public.projects
  for each row execute function public.set_updated_at();
create trigger clips_set_updated_at before update on public.project_clips
  for each row execute function public.set_updated_at();
create trigger keys_set_updated_at before update on public.user_api_keys
  for each row execute function public.set_updated_at();

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email, display_name, avatar_url)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name'),
    new.raw_user_meta_data ->> 'avatar_url'
  );
  insert into public.analytics_events (user_id, event_name)
  values (new.id, 'signup_completed');
  return new;
end;
$$;

revoke execute on function public.handle_new_user() from public, anon, authenticated;

create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

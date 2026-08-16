-- ONMC hosted knowledge base — Supabase (Postgres + pgvector)
-- Apply in the Supabase SQL editor (or `supabase db push`).
--
-- Design: the hosted store persists only what earned its place locally —
-- promoted memories (with their full authorization trail), the measured
-- ledger, and attested receipts. Verification stays local; hosting is
-- distribution, never judgment.

create extension if not exists vector;

-- Promoted memories: nothing lands here without a promotion record.
create table if not exists earned_memories (
  memory_id   text primary key,
  org_id      uuid not null default auth.uid(),
  kind        text not null check (kind in
                ('episode','repo-fact','decision','failed-approach','skill','strategy')),
  content     text not null,
  scope       jsonb not null,            -- repo/branch/path/language/task globs
  provenance  jsonb not null,            -- trace/artifact refs from the verified run
  version     integer not null,
  promotion   jsonb not null,            -- PromotionRecord: evidence, gate verdicts
  embedding   vector(1536),              -- optional; filled by the embed worker
  created_at  timestamptz not null default now(),
  retired_at  timestamptz                -- evidence-based retirement, never deletion
);

-- The measured P&L per memory/skill (attribution output).
create table if not exists memory_ledger (
  memory_id   text not null references earned_memories(memory_id),
  measured_at timestamptz not null default now(),
  mean_lift   double precision not null,
  ci_low      double precision not null,
  ci_high     double precision not null,
  n_tasks     integer not null,
  verdict     text not null check (verdict in ('earning','harmful','unproven')),
  primary key (memory_id, measured_at)
);

-- Attested receipts (in-toto/DSSE envelopes) — the audit trail.
create table if not exists receipts (
  receipt_hash text primary key,
  org_id       uuid not null default auth.uid(),
  repo         text not null,
  verified     boolean not null,
  envelope     jsonb not null,           -- DSSE envelope incl. signatures
  created_at   timestamptz not null default now()
);

-- Row-level security: every org sees only its own rows.
alter table earned_memories enable row level security;
alter table memory_ledger enable row level security;
alter table receipts enable row level security;

create policy org_isolation_memories on earned_memories
  using (org_id = auth.uid()) with check (org_id = auth.uid());
create policy org_isolation_receipts on receipts
  using (org_id = auth.uid()) with check (org_id = auth.uid());
create policy org_isolation_ledger on memory_ledger
  using (exists (select 1 from earned_memories m
                 where m.memory_id = memory_ledger.memory_id
                   and m.org_id = auth.uid()));

-- ANN index for recall once embeddings are populated.
create index if not exists earned_memories_embedding_idx
  on earned_memories using ivfflat (embedding vector_cosine_ops) with (lists = 100);

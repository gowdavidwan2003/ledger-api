-- Transaction Ledger schema.
--
-- Names are unqualified: scripts/migrate.py sets search_path to the target schema
-- first, so this one file builds `ledger` for the app and `ledger_test` for tests.
--
-- Business rules live in Python (app/domain/rules.py). The database enforces the
-- invariants that must hold no matter what code runs against it.

-- Time-ordered UUIDs (v7): new rows append to the right edge of the primary-key
-- index instead of landing on random pages, which keeps inserts cheap as tables
-- grow. Postgres 18 has uuidv7() built in; this works on 13+.
create function uuid_generate_v7() returns uuid
language sql volatile
set search_path from current
as $$
  select encode(
    set_bit(
      set_bit(
        overlay(uuid_send(gen_random_uuid())
                placing substring(int8send((extract(epoch from clock_timestamp()) * 1000)::bigint) from 3)
                from 1 for 6),
        52, 1),
      53, 1),
    'hex')::uuid;
$$;

create type txn_type as enum ('credit', 'debit');

create table accounts (
  id          uuid        primary key default uuid_generate_v7(),
  name        text        not null check (length(btrim(name)) between 1 and 100),
  balance     bigint      not null default 0,   -- minor units (paise)
  created_at  timestamptz not null default now(),
  constraint accounts_balance_non_negative check (balance >= 0)
);

create table transactions (
  id            uuid        primary key default uuid_generate_v7(),
  account_id    uuid        not null references accounts(id),
  type          txn_type    not null,
  amount        bigint      not null check (amount > 0),
  description   text        not null check (length(description) between 1 and 255),
  reference_id  text        not null check (length(reference_id) between 1 and 100),
  balance_after bigint      not null check (balance_after >= 0),
  created_at    timestamptz not null default now(),
  -- reference_id is the client's idempotency key, unique within an account.
  constraint transactions_account_reference_uniq unique (account_id, reference_id)
);

-- History: newest first, keyset-paginated on (created_at, id).
create index transactions_account_created_idx
  on transactions (account_id, created_at desc, id desc);

-- Ledger rows are append-only. Corrections are new transactions, never edits.
create function forbid_transaction_changes() returns trigger
language plpgsql
as $$
begin
  raise exception 'transactions are append-only (% blocked)', tg_op
    using errcode = 'restrict_violation';
end;
$$;

create trigger transactions_append_only
  before update or delete on transactions
  for each row execute function forbid_transaction_changes();

-- Supabase hardening (harmless on plain Postgres): RLS with no policies means the
-- anon/authenticated API keys see nothing. The backend connects as the table
-- owner, which RLS does not apply to.
alter table accounts enable row level security;
alter table transactions enable row level security;

do $$
begin
  execute format('revoke all on schema %I from public', current_schema());
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute format('revoke all on schema %I from anon, authenticated', current_schema());
  end if;
end;
$$;

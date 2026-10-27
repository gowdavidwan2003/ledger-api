-- Least privilege for the application, and a TRUNCATE guard.

-- 1. A dedicated role holding only what the API needs. The API connects as the
--    owner and immediately runs SET ROLE ledger_app (app/db.py), so a bug or an
--    injected statement can't drop tables, disable triggers or rewrite history.
--
--    SET ROLE limits what the app *does*; it isn't a wall against an attacker who
--    can run arbitrary SQL, because RESET ROLE undoes it. For that, give the role
--    LOGIN and a password and put it in DATABASE_URL directly (see docs/DESIGN.md).
--    Roles are cluster-wide, so create it only once.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'ledger_app') then
    create role ledger_app nologin;
  end if;
  execute format('grant ledger_app to %I', current_user);
end;
$$;

do $$
begin
  execute format('grant usage on schema %I to ledger_app', current_schema());
end;
$$;

grant select, insert on accounts to ledger_app;
grant update (balance) on accounts to ledger_app;        -- the only column the app ever changes
grant select, insert on transactions to ledger_app;      -- no update, no delete, no truncate
grant execute on function uuid_generate_v7() to ledger_app;

-- RLS is on for both tables (001). Policies let the app role see every row; the
-- Supabase API roles still have no policy and so see nothing.
create policy ledger_app_all on accounts to ledger_app using (true) with check (true);
create policy ledger_app_all on transactions to ledger_app using (true) with check (true);

-- 2. The append-only trigger in 001 is per row, and TRUNCATE fires no row
--    triggers. A statement-level trigger closes that gap for both tables
--    (TRUNCATE accounts CASCADE would also empty transactions).
create trigger transactions_no_truncate
  before truncate on transactions
  for each statement execute function forbid_transaction_changes();

create trigger accounts_no_truncate
  before truncate on accounts
  for each statement execute function forbid_transaction_changes();

-- Accounts are identified to people by mobile number (stored as E.164, +91XXXXXXXXXX).
--
-- Added as NOT NULL directly because no accounts existed when this shipped. On a
-- table with rows this would be three steps: add nullable, backfill, set not null.
alter table accounts add column phone text not null;

alter table accounts
  add constraint accounts_phone_format check (phone ~ '^\+91[6-9][0-9]{9}$');

-- One account per number; also serves the lookup-by-phone query.
alter table accounts
  add constraint accounts_phone_uniq unique (phone);

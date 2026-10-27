# Transaction Ledger API

A backend for a simple ledger: create accounts, post credits and debits, read balances and history. Includes a small Streamlit UI on top of the API.

**FastAPI · psycopg 3 · PostgreSQL (Supabase) · pytest · Streamlit · GitHub Actions**

| Streamlit UI | Swagger docs (`/docs`) |
|---|---|
| ![UI](docs/screenshots/ui-history.jpg) | ![Swagger](docs/screenshots/swagger.jpg) |

## Highlights

- **Money is never a float.** Amounts are stored as integer paise and exchanged as `"150.00"` strings.
- **No lost updates under concurrency.** Every balance change runs in one DB transaction holding a row lock. 20 parallel ₹10 debits against ₹100 → exactly 10 succeed. That's tested.
- **Safe retries.** `reference_id` is an idempotency key, unique per account. A retried request returns the original transaction (`200`) instead of charging twice.
- **The database enforces the invariants too:** `balance >= 0`, positive amounts, unique references, append-only transactions. A bug in the app still can't corrupt the ledger.
- **Security-reviewed and hardened:**
  - the app runs as a least-privilege database role;
  - truncates are blocked, and DB timeouts stop stuck locks hanging requests;
  - request bodies are capped (413);
  - unsafe text and request IDs are rejected or replaced;
  - user text is escaped in the UI.

  Each fix has a test. See [docs/DESIGN.md §10](docs/DESIGN.md#10-security-hardening).
- **Customers use a mobile number, never an internal ID.** Sign-up and lookup are by phone, normalised so `98765 43210`, `+91-98765-43210` and `098765 43210` match. Responses only ever show it masked (`+91 ******3210`).
- **183 tests:** 140 unit tests (no DB, ~2s) and 43 integration tests on real Postgres, including race-condition, privilege and timeout tests. Lint and tests run in CI on every push.

**Demo login:** dummy number `9000000001` (account "Vidwan Gowda"). Any 10-digit number starting 6–9 can be used to sign up. No OTP or SMS is sent.

## Quick start

```bash
py -3.12 -m venv .venv && .venv\Scripts\activate     # macOS/Linux: python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                                  # paste your Postgres / Supabase session-pooler URL
python scripts/migrate.py                             # creates schema "ledger"; safe to re-run
uvicorn app.main:app --reload                         # http://localhost:8000/docs
streamlit run ui/streamlit_app.py                     # http://localhost:8501
python scripts/seed_demo.py                           # optional: demo account "Vidwan Gowda", log in with 9000000001
```

```bash
pytest tests/unit          # no database needed
pytest                     # everything; integration tests use an isolated "ledger_test" schema
ruff check . && ruff format --check .
```

Any Postgres 13+ works. For a throwaway local one: `docker run -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:17`, with `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres`.

## Deploying on Streamlit Community Cloud

Streamlit Cloud runs a single process, so the hosted app starts the FastAPI service inside it on a background thread (`ui/embedded_api.py`). The UI still calls it over HTTP, unchanged.

1. On [share.streamlit.io](https://share.streamlit.io), click **Create app**, pick this repo and branch `main`, and set the main file to `ui/streamlit_app.py`.
2. Under **Advanced settings**, choose Python **3.12** and paste the secrets from [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example), filled in. Set `EMBED_API = "1"` and use the Supabase session-pooler `DATABASE_URL`.
3. Deploy. The migrations must already have been applied to that database (`python scripts/migrate.py`).

## API

Interactive docs at **`/docs`** (Swagger) list every request, response and error.

| Method | Path | Success | Errors |
|---|---|---|---|
| POST | `/accounts` | **201** account | 400 · 409 |
| POST | `/accounts/lookup` | **200** account for a phone number | 400 · 404 |
| GET | `/accounts/{id}` | **200** account | 400 · 404 |
| GET | `/accounts/{id}/balance` | **200** `{account_id, balance}` | 400 · 404 |
| POST | `/accounts/{id}/transactions` | **201** created · **200** replay | 400 · 404 · 409 · 422 |
| GET | `/accounts/{id}/transactions?limit&cursor&type` | **200** page, newest first | 400 · 404 |
| GET | `/health` | **200** | 503 |

**Status codes** (the main ones; **every error code, when it happens, its `details` and whether to retry → [docs/ERRORS.md](docs/ERRORS.md)**):

| Code | Meaning |
|---|---|
| `400 VALIDATION_ERROR` | Malformed or missing input, including any attempt to set `balance`, `id` or `created_at` |
| `404 ACCOUNT_NOT_FOUND` | No account with that id |
| `404 PHONE_NOT_REGISTERED` | No account for that phone number |
| `409 PHONE_ALREADY_REGISTERED` | That phone number already has an account, in any format |
| `409 REFERENCE_ID_CONFLICT` | `reference_id` was already used on this account for a *different* transaction |
| `422 INSUFFICIENT_FUNDS` | The request is valid, but the debit is larger than the balance. Nothing is written. |
| `503 DATABASE_UNAVAILABLE` | Safe to retry |

Every error has the same shape, and every response carries an `X-Request-ID`:

```json
{"error": {"code": "INSUFFICIENT_FUNDS", "message": "Debit rejected: balance is lower than the amount",
           "details": {"balance": "50.00", "requested": "100.00"}}}
```

### Walkthrough

```bash
curl -X POST localhost:8000/accounts -H "Content-Type: application/json" -d '{"name":"Vidwan Gowda","phone":"9000000001"}'
# 201 {"id":"019a…","name":"Vidwan Gowda","phone":"+91 ******0001","balance":"0.00","created_at":"…"}

curl -X POST localhost:8000/accounts/lookup -H "Content-Type: application/json" -d '{"phone":"+91 90000 00001"}'
# 200 the same account (any format of the number works)

curl -X POST localhost:8000/accounts/$ID/transactions -H "Content-Type: application/json" \
     -d '{"type":"credit","amount":"100.00","description":"Salary","reference_id":"salary-oct"}'
# 201 {"type":"credit","amount":"100.00","balance_after":"100.00",…}

# same request again (network retry)
# 200 + Idempotent-Replayed: true, same body, balance still 100.00

curl -X POST localhost:8000/accounts/$ID/transactions -H "Content-Type: application/json" \
     -d '{"type":"debit","amount":"250.00","description":"Rent","reference_id":"rent-oct"}'
# 422 INSUFFICIENT_FUNDS, balance still 100.00

curl "localhost:8000/accounts/$ID/transactions?limit=20"
# {"data":[…newest first…],"next_cursor":null}
```

## Architecture

```
app/
├── api/            HTTP only: routes, request/response schemas, error mapping
├── services/       use cases; owns the DB transaction and the row lock
├── domain/         pure business rules: models, money, rules.decide(), errors (no I/O)
├── repositories/   SQL, one module per table
├── db.py           connection pool
├── observability.py  request IDs + JSON logs
└── main.py         app factory
db/migrations/      versioned SQL, applied once each by scripts/migrate.py
tests/unit/         rules, money, pagination, full HTTP contract against an in-memory fake
tests/integration/  real Postgres: flows, races, DB invariants, migrations
ui/                 Streamlit; talks only to the HTTP API
```

**Posting a transaction:**

```
BEGIN
  SELECT balance FROM accounts WHERE id = $1 FOR UPDATE      -- other requests for this account wait here
  SELECT … FROM transactions WHERE account_id = $1 AND reference_id = $2
  rules.decide(balance, request, existing)  →  Apply(new_balance) | Replay(original) | raise
  UPDATE accounts SET balance = $new
  INSERT INTO transactions (…, balance_after = $new)
COMMIT
```

`rules.decide` is a pure function. Every business rule is unit-tested without a database, and the service layer only handles I/O.

**Why each design choice, and what I'd change at scale →** [docs/DESIGN.md](docs/DESIGN.md)

## Validation

| Field | Rule |
|---|---|
| `name` | required, trimmed, 1–100 chars |
| `phone` | required, 10-digit Indian mobile starting 6–9; `+91`/`0` prefix, spaces and dashes OK; unique |
| `type` | `credit` \| `debit` |
| `amount` | number or string, > 0, ≤ 1,000,000,000, at most 2 decimals |
| `description` | required, trimmed, 1–255 chars |
| `reference_id` | required, trimmed, 1–100 chars, unique per account |

Unknown fields are rejected, so typos like `amout` fail loudly instead of being ignored.

## Assumptions

- **Single currency with 2 decimal places.** The UI shows ₹; the API itself is currency-agnostic.
- **Phone lookup is identification, not authentication.** No OTP is sent, so use dummy numbers. In production, lookup would sit behind OTP verification and issue a session token. It's a POST so numbers stay out of URLs and access logs.
- **The UI hides internal identifiers.** Account IDs never appear on screen. A transaction's reference ID is shown only once the transaction succeeds, as its receipt; declined attempts show none.
- **Not in scope:** authentication/authorisation, account closure, and transfers between accounts. A transfer would be two postings in one DB transaction, locking both account rows in id order to avoid deadlocks.
- **Supabase free-tier note:** the session pooler allows 15 client connections. The app pool defaults to 10.

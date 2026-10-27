# Error reference

Every error response has the same shape, whichever endpoint returns it:

```json
{
  "error": {
    "code": "INSUFFICIENT_FUNDS",
    "message": "Debit rejected: balance is lower than the amount",
    "details": { "balance": "50.00", "requested": "100.00" }
  }
}
```

- **`code`** is stable and machine-readable. Clients should branch on this, never on `message`.
- **`message`** is human-readable and may be reworded.
- **`details`** is extra context, or `null`. Its shape depends on the code (see below).
- Every response, error or not, carries an **`X-Request-ID`** header. Quote it when reporting a problem; it matches the server log line for that request.

## Summary

| HTTP | Code | Reason | Retry? |
|---|---|---|---|
| 400 | `VALIDATION_ERROR` | The request body, path or query is malformed, missing a field, or has an extra one | No, fix the request |
| 400 | `INVALID_CURSOR` | The pagination `cursor` wasn't issued by this API | No, start from the first page |
| 400 | `BAD_REQUEST` | Fallback for a rejected request with no more specific code | No |
| 404 | `ACCOUNT_NOT_FOUND` | No account has this `account_id` | No |
| 404 | `PHONE_NOT_REGISTERED` | No account has this phone number | No, sign up instead |
| 404 | `NOT_FOUND` | The URL doesn't match any endpoint | No, check the path |
| 405 | `METHOD_NOT_ALLOWED` | The endpoint exists but not with this HTTP method | No |
| 413 | `PAYLOAD_TOO_LARGE` | The request body is over the size limit (16 KB by default) | No, send a smaller body |
| 409 | `PHONE_ALREADY_REGISTERED` | Sign-up with a number that already has an account | No, log in instead |
| 409 | `REFERENCE_ID_CONFLICT` | `reference_id` was already used on this account for a different transaction | Yes, with a **new** `reference_id` if it really is a new transaction |
| 422 | `INSUFFICIENT_FUNDS` | The debit is larger than the current balance | After the balance increases |
| 500 | `INTERNAL_ERROR` | An unexpected server bug | Yes; report the `X-Request-ID` if it persists |
| 503 | `DATABASE_UNAVAILABLE` | The database can't be reached right now | Yes, with backoff |
| other | `HTTP_ERROR` | Any other HTTP-level error from the framework | Depends on status |

**Why 400 and 422 are different:** a 400 means "this request is malformed, fix it". A 422 means "the request is valid, but the business rules won't allow it right now". Clients usually handle these differently: fix the form versus tell the user their balance is too low.

## Details by code

### 400 `VALIDATION_ERROR`

**When:** a field fails validation. For example:
- a name that is missing, blank or over 100 characters
- a phone that isn't a 10-digit Indian mobile starting 6–9
- `type` other than `credit`/`debit`
- an amount that is ≤ 0, over 1,000,000,000, has more than 2 decimals, or isn't a number
- a blank or over-long `description`/`reference_id`
- a malformed UUID in the path
- `limit` outside 1–100
- **any unknown field**, including attempts to set `balance`, `id` or `created_at`
- control characters (NUL, newline, tab, etc.) in `name`, `description` or `reference_id`
- a phone number written with non-ASCII digits (e.g. full-width `９`), or with trailing whitespace or a newline

As a safety net, a value that passes validation but is still refused by the database's own type rules also returns `VALIDATION_ERROR` (with `details: null`) instead of a 500.

**Nothing is written.**

`details` is a list with one entry per problem:

```json
{"error": {"code": "VALIDATION_ERROR", "message": "Request validation failed",
  "details": [{"field": "balance", "message": "Extra inputs are not permitted"},
              {"field": "phone", "message": "Value error, must be a 10-digit Indian mobile number starting with 6-9"}]}}
```

### 400 `INVALID_CURSOR`

**When:** `GET /accounts/{id}/transactions?cursor=…` receives a cursor that can't be decoded. Cursors are opaque: only pass back a `next_cursor` from an earlier response. `details`: `null`.

### 400 `BAD_REQUEST`

**When:** a business-rule rejection that has no dedicated code. Every current rule has one, so this is a safety net that shouldn't appear in practice. `details`: `null`.

### 404 `ACCOUNT_NOT_FOUND`

**When:** any `/accounts/{account_id}/…` route gets a well-formed UUID that matches no account. `details`: `null`.

### 404 `PHONE_NOT_REGISTERED`

**When:** `POST /accounts/lookup` with a valid number that no account uses. `details`: `null`.

### 404 `NOT_FOUND` / 405 `METHOD_NOT_ALLOWED`

**When:** the URL or HTTP method doesn't match any route, e.g. `DELETE /accounts/{id}`. Accounts and transactions can't be deleted. `details`: `null`.

### 413 `PAYLOAD_TOO_LARGE`

**When:** the request body is larger than `MAX_BODY_BYTES` (16,384 bytes by default; the largest legitimate request is well under 1 KB). Bodies that declare a larger `Content-Length` are refused before any of the body is read. Chunked bodies are counted as they arrive and cut off at the limit, so the server never buffers an oversized body. **Nothing is written.** `details`: `null`.

### 409 `PHONE_ALREADY_REGISTERED`

**When:** `POST /accounts` with a number that already has an account. Numbers are normalised first, so `9000000001`, `+91 90000 00001` and `090000 00001` all collide. **Nothing is written.** `details`: `null`.

### 409 `REFERENCE_ID_CONFLICT`

**When:** `POST /accounts/{id}/transactions` reuses a `reference_id` that this account already used, but with a different `type`, `amount` or `description`. **Nothing is written.**

```json
{"error": {"code": "REFERENCE_ID_CONFLICT",
  "message": "reference_id was already used on this account for a different transaction",
  "details": {"existing_transaction_id": "019a…"}}}
```

This is **not** an error for an identical retry. A repeat with the same reference and the same payload returns **200** with the original transaction and the header `Idempotent-Replayed: true`. It is never applied twice.

### 422 `INSUFFICIENT_FUNDS`

**When:** a debit is larger than the current balance. A debit of exactly the balance is allowed and leaves 0.00. **Nothing is written**, and the `reference_id` isn't used up, so the same request can succeed after a top-up.

```json
{"error": {"code": "INSUFFICIENT_FUNDS", "message": "Debit rejected: balance is lower than the amount",
  "details": {"balance": "50.00", "requested": "100.00"}}}
```

### 500 `INTERNAL_ERROR`

**When:** an unexpected exception. The response never includes stack traces or internal messages. The full error is logged server-side under the request's `X-Request-ID`. `details`: `null`.

### 503 `DATABASE_UNAVAILABLE`

**When:** one of these:
- the database connection fails;
- the request waited more than **3 s** for another request's lock on the same account (`lock_timeout`);
- a single statement ran longer than **5 s** (`statement_timeout`).

Timed-out requests are rolled back, so nothing was applied. After a connection failure the outcome can be unknown, so **retry with the same `reference_id`**. Idempotency then guarantees the result is applied once. `details`: `null`.

## Error codes by endpoint

| Endpoint | Possible codes |
|---|---|
| `POST /accounts` | `VALIDATION_ERROR`, `PHONE_ALREADY_REGISTERED` |
| `POST /accounts/lookup` | `VALIDATION_ERROR`, `PHONE_NOT_REGISTERED` |
| `GET /accounts/{id}` | `VALIDATION_ERROR`, `ACCOUNT_NOT_FOUND` |
| `GET /accounts/{id}/balance` | `VALIDATION_ERROR`, `ACCOUNT_NOT_FOUND` |
| `POST /accounts/{id}/transactions` | `VALIDATION_ERROR`, `ACCOUNT_NOT_FOUND`, `REFERENCE_ID_CONFLICT`, `INSUFFICIENT_FUNDS` |
| `GET /accounts/{id}/transactions` | `VALIDATION_ERROR`, `INVALID_CURSOR`, `ACCOUNT_NOT_FOUND` |
| `GET /health` | `DATABASE_UNAVAILABLE` |
| any | `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `PAYLOAD_TOO_LARGE`, `INTERNAL_ERROR`, `DATABASE_UNAVAILABLE` |

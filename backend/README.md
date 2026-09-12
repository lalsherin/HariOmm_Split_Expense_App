# Split Ledger API

Mobile-number identity and cross-device sync, so a group created on one phone
shows up on everyone else's.

FastAPI · SQLAlchemy (async) · PostgreSQL · Docker. No Redis — see *Rate
limiting* below.

---

## ⚠️ Read this before it is reachable from the internet

This server ships with **`REQUIRE_OTP=false`**, a deliberate choice for the
first version. It means:

> **Anyone who types a mobile number becomes that person** — their account,
> their groups, every expense in them.

That is workable for a handful of people who know each other and a server that
is not advertised. It is **not safe for a public app**. Everything needed to
close it is already here: set `REQUIRE_OTP=true`, point `SMS_PROVIDER` at a
real provider, and the flow becomes number → code → verified. No code changes.
For Indian numbers you will also need a DLT-registered sender ID and an
approved template, which takes days to obtain.

The server logs a warning on every boot while verification is off.

---

## Running it

### Docker (recommended)

```sh
cp .env.example .env          # then edit it
POSTGRES_PASSWORD=something-long docker compose up --build
```

API on `http://localhost:8000`, interactive docs at `/docs`.

### Without Docker

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
```

With no `DATABASE_URL` it falls back to a local SQLite file, which is fine for
trying it out and is what the tests use.

### Tests

```sh
pip install -r requirements-dev.txt
pytest -q
```

43 tests: phone normalisation, register/login, token rotation and theft
detection, logout, rate limiting, the OTP flow with verification switched on,
and the sync behaviour that the whole thing exists for.

---

## Endpoints

| | |
|---|---|
| `POST /auth/request-otp` | Send a code. No-op while `REQUIRE_OTP=false`. Never reveals whether a number already has an account. |
| `POST /auth/sign-in` | Register **or** log in — one door for both. Returns access + refresh tokens and the user. |
| `POST /auth/refresh-token` | Rotate the pair. The old refresh token is burned. |
| `POST /auth/logout` | Revoke the current session. |
| `GET /auth/me`, `GET /users/me` | The signed-in user. |
| `GET /users/me/logins` | Recent sign-in history for this account. |
| `POST /sync` | Push local changes, pull everything new. The one endpoint the app calls in normal use. |
| `GET /health` | Liveness, plus whether OTP is on. |

---

## How sync works

The phone is the source of truth for what its owner typed; the server is the
meeting point. Neither waits for the other, so the app keeps working with no
signal and reconciles later.

```
POST /sync  { since: <last seq seen>, changes: { groups, members, expenses, settlements } }
         ->  { seq: <new high-water mark>, groups, members, expenses, settlements, rejected }
```

**`seq`, not timestamps.** Every write stamps the row with a global counter.
A phone asks for "everything above the number I last saw". Two phones with
badly-set clocks can still never miss each other's changes — which is exactly
what a timestamp cursor gets wrong.

**Tombstones.** Nothing is hard-deleted. A phone that was offline for a week
has to be able to learn that an expense went away, and silence cannot tell it
that.

**Conflicts resolve last-writer-wins** on each row's `updated_at`. An older
edit arriving late is discarded rather than clobbering a newer one. For
expense rows — usually edited by one person, shortly after creating them —
this is the right amount of machinery. Anything finer (per-field merge, or
CRDTs) would cost far more than it returns here.

**Access control.** You can read and write a group if you are a member of it,
or created it. Writes into a group you are not in are returned in `rejected`
rather than silently dropped, so the app can tell you.

### How a group reaches someone

1. Sherin adds "Anu, +91 98765 00002" to a group. That member row carries the
   normalised number.
2. Anu installs the app and signs in with that number.
3. On sign-in the server claims every member row waiting for it, links them to
   her new account, and re-stamps their `seq`.
4. Anu's first `/sync` returns the group, its members and its whole expense
   history. The other phones learn that the placeholder is now a real person.

Because the link is the phone number, normalisation has to be exact —
`9876543210`, `098765 43210` and `+91-98765-43210` are all one person. That is
`app/phone.py`, and it is tested from both ends.

---

## Design decisions worth knowing

**Opaque tokens, not JWTs.** Section 9 of the spec allows "an equivalent
secure session architecture". Opaque random tokens are the better trade here:
a lost phone is revoked with one `UPDATE`, whereas a self-contained JWT stays
valid until it expires unless you add a denylist — which puts back the
database lookup JWTs exist to avoid. Tokens are stored only as SHA-256 hashes,
so a dump of the `sessions` table cannot be replayed.

**Refresh-token theft detection.** Refresh tokens rotate on every use. If a
spent one is presented again, that means a copy exists, so *every* session for
that user is revoked rather than leaving the thief holding a live one.

**Rate limiting in Postgres, not Redis.** The spec suggests Redis. Against a
single instance and 10,000 users, a table avoids running a second piece of
infrastructure for one counter. `app/middleware/rate_limit.py` is one function
— swap it for `INCR`/`EXPIRE` when you run more than one process.

**Money is integers.** Every amount is in minor units (paise), never floats.

---

## Known gaps

- **No migrations.** Tables are created on startup. That is fine for the first
  deploy, but a change to a live schema needs Alembic adding. Called out here
  rather than pretended away.
- **`account_status`** is enforced on sign-in and on every authenticated
  request, but there is no admin endpoint to set it yet.
- **No pagination on `/sync`.** A first sync for an account in a very large
  group returns everything in one response. Fine at this scale; add a page
  size if a group ever holds tens of thousands of expenses.
- **`X-Forwarded-For` is trusted** for IP rate limiting. Make sure your proxy
  overwrites it, or the IP limit is bypassable.

# Putting the sync server online

Until a server exists, every phone is an island: the app stores everything in
`localStorage` and the status bar reads **This phone only**. Nothing syncs, no
matter who adds whose number.

This is how to change that. Budget about 40 minutes the first time.

What you end up with: a `https://…onrender.com` address that both phones paste
into **Account → Sync server**, and a Postgres database that outlives the free
trial of whichever host you picked.

---

## The shape of it

```
   Phone A  ─┐
             ├─► https://split-ledger.onrender.com   ─►  Neon Postgres
   Phone B  ─┘        (Render web service)               (Singapore)
```

Two accounts, both free to start: **Neon** for the database, **Render** for the
API. They are separate on purpose — Render's own free Postgres is deleted 30
days after you create it, which is a bad surprise to discover with real data in
it. Neon's free database has no expiry.

Put both in **Singapore**. It is the closest region to India on either
platform, and the app↔database hop happens on every request.

---

## 1 — The database (Neon)

1. Sign up at **neon.com**.
2. Create a project. Name it `split-ledger`; region **AWS ap-southeast-1
   (Singapore)**.
3. On the dashboard, copy the connection string. It looks like:

   ```
   postgresql://neondb_owner:npg_XXXX@ep-cool-name-12345678.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require
   ```

   **Take the direct string, not the pooled one.** The pooled host has
   `-pooler` in it and runs pgbouncer in transaction mode, which breaks
   asyncpg's prepared statements. With a handful of users you do not need the
   pooler.

Paste it exactly as Neon prints it. The server rewrites the scheme and the TLS
parameters for you on startup — `normalise_database_url()` in `app/config.py`,
covered by tests.

Free plan: 0.5 GB storage, 100 compute-hours a month, and the database sleeps
after 5 minutes idle and wakes in well under a second. For a few friends'
expenses this is not close to a limit.

---

## 2 — The API (Render)

1. Sign up at **render.com** and connect your GitHub account.
2. **New → Web Service**, pick `lalsherin/HariOmm_Split_Expense_App`.
3. Settings:

   | Field | Value |
   |---|---|
   | Name | `split-ledger` (this becomes the URL) |
   | Region | Singapore |
   | Root Directory | `backend` |
   | Language / Runtime | **Docker** |
   | Dockerfile Path | `./Dockerfile` (relative to the root directory) |
   | Instance Type | see the cold-start note below |

   Render sets `PORT` itself and the Dockerfile binds to it.

4. Add environment variables:

   ```
   DATABASE_URL          <the Neon string from step 1>
   DEFAULT_COUNTRY_CODE  +91
   REQUIRE_OTP           false
   CORS_ORIGINS          *
   RL_AUTH_PER_IP        2000
   LOG_LEVEL             INFO
   ```

   `RL_AUTH_PER_IP` defaults to 30 per hour, which does not survive Indian
   mobile networks — Jio and Airtel put enormous numbers of subscribers behind
   a handful of public IPs, so that limit would be shared with strangers. The
   per-number limit (10/hour) is the one doing real work.

5. Deploy. The first build takes a few minutes.

6. Check it:

   ```
   https://split-ledger.onrender.com/health
   →  {"status":"ok","otp_required":false}
   ```

   Tables are created automatically on first startup. There are no migrations
   in this repo yet, so a future schema change will need Alembic or a manual
   `DROP`.

### The cold-start problem

Render's **free** instance sleeps after 15 minutes of inactivity and takes
30–60 seconds to wake. The app gives up on a request after 20 seconds. So on
free, the first sync after a quiet spell shows *"No connection — changes are
saved here and will sync later"*, and the next one (two minutes later, or when
you tap Account → Save) works. Nothing is lost; it just looks broken the first
time.

**Starter, at $7/month, never sleeps.** If anyone other than you is going to
use this, pay the $7. It is the single biggest difference between "our expense
app" and "that app that never works".

---

## 3 — Point the phones at it

On **each** phone, including yours:

1. Open Split Ledger.
2. Tap **Account**, next to the status dot at the top.
3. Put the address in **Sync server**:
   `https://split-ledger.onrender.com` — no trailing slash, and `https`.
4. **Save.**

The dot should turn green and read **Synced**. If it says *Sync problem*, the
message underneath is the server's own words.

---

## 4 — Prove it works

1. On phone A, create a group and add phone B's mobile number as a member.
2. On phone B, open the app. Within about two minutes the group appears. To
   stop waiting, tap **Account → Save** to force a sync.
3. Add an expense on B; it shows up on A.

If B sees nothing, in order of likelihood:

- **B never signed in with that exact number.** The member row waits for
  whoever signs in with it. `+91 98765 43210` and `98765 43210` are the same
  number to the app; a *different* number is a different person.
- **B's server address is missing or misspelt.** Check Account on B.
- **A's group never reached the server.** A's status dot should read *Synced*,
  not *This phone only*.
- **The app is in the background on B.** It only polls while on screen.

---

## What this still is not

`REQUIRE_OTP=false` means **anyone who types a mobile number becomes that
person**. There is no verification. For you and your friends that is a
reasonable trade; the moment a stranger can reach the URL it is not. Turning it
on needs an SMS provider and, for Indian numbers, DLT registration — a
regulatory step, not a code change.

Two known defects worth fixing before real users arrive, both found by the
load test in `claude/split-ledger-load-test.md`:

- the rate limiter's get-then-INSERT race returns **500** instead of 429 when
  two requests create the same counter at once;
- an idle sync costs 12 queries and a write; four small changes take it to
  about three queries and none.

Neither matters at two users. Both matter at two hundred.

---

## Running costs

| | Free | Comfortable |
|---|---|---|
| Neon Postgres | ₹0 | ₹0 (free tier is ample here) |
| Render web service | ₹0, sleeps after 15 min | $7/mo ≈ ₹620, always warm |
| Domain (optional) | — | ~₹1,000/year |

Sources: [Render free tier](https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026),
[Neon plans](https://neon.com/docs/introduction/plans).

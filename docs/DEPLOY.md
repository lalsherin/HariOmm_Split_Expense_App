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

`render.yaml` at the root of this repository already describes the service —
region, Docker settings, health check and every environment variable. Render
reads it, so there is no form to fill in and nothing to mistype.

**First make sure the repo on GitHub is current**, including `render.yaml`.
Run `push_to_github.cmd` from the extracted project folder if in doubt; Render
reads GitHub, not your laptop.

1. Go to **dashboard.render.com**.
2. **New +** (top right) → **Blueprint**.
3. If Render has not seen your GitHub account yet it asks to connect. Approve
   it, and give it access to `HariOmm_Split_Expense_App` — "Only select
   repositories" is enough; it does not need the rest of your account.
4. Pick **`lalsherin/HariOmm_Split_Expense_App`** → **Connect**.
5. Render finds `render.yaml` and shows one service, **split-ledger**, plus a
   single field to fill in: **DATABASE_URL**. Paste the Neon string from step
   1 there.
6. **Apply** / **Create Resources**.

The first build takes three to five minutes — Render pulls the Python image,
installs the requirements and starts uvicorn. Watch the **Logs** tab. You are
looking for:

```
Application startup complete.
Uvicorn running on http://0.0.0.0:10000
```

A `WARNING … REQUIRE_OTP is off` line above it is expected and correct.

7. Your address is on the service page, `https://split-ledger.onrender.com` or
   similar (Render adds a suffix if the name is taken — use whatever it shows).
   Open it with `/health` on the end:

   ```
   https://split-ledger.onrender.com/health
   →  {"status":"ok","otp_required":false}
   ```

Tables are created automatically on first startup. There are no migrations in
this repo yet, so a future schema change will need Alembic or a manual `DROP`.

### If you would rather click through it by hand

**New + → Web Service** instead of Blueprint, then set: Region **Singapore**,
Root Directory **`backend`**, Language **Docker**, Dockerfile Path
**`./Dockerfile`**, Health Check Path **`/health`**, and add the six
environment variables listed in `render.yaml` yourself. Render sets `PORT` and
the Dockerfile binds to it.

Dockerfile Path is resolved **relative to the Root Directory**, so with
`backend` as the root the path is `./Dockerfile`. Writing
`./backend/Dockerfile` makes Render look for `backend/backend/Dockerfile` and
the deploy dies at the clone step with `lstat …/backend/backend: no such file
or directory`.

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

To switch later: the service's **Settings → Instance Type**, or change
`plan: free` to `plan: starter` in `render.yaml` and push.

---

## 3 — Point the phones at it

On **each** phone, including yours:

1. Open Split Buddy.
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

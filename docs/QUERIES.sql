-- ============================================================
--  Split Buddy — queries for the Neon SQL editor
--
--  console.neon.tech -> project still-voice-88708648 -> SQL Editor
--  Paste one query at a time and press Run.
--
--  Everything here is READ-ONLY except the clearly marked section at
--  the bottom. Nothing in this file prints a password or a token: the
--  connection string lives in Render's environment, never here.
--
--  Two columns — users.last_seen_at and users.app_version — only exist
--  once a build of 3.5 or later has been deployed to Render. Before
--  that, drop them from the SELECT and the rest still works.
-- ============================================================


-- ------------------------------------------------------------
--  1. Who has signed up
--     The main one. Most recently active first.
-- ------------------------------------------------------------
select name,
       mobile_number,
       app_version,
       created_at,
       last_login_at,
       last_seen_at,
       account_status
from users
order by last_seen_at desc nulls last;


-- ------------------------------------------------------------
--  2. "My friend says it won't let him in"
--     Every sign-in ATTEMPT, including the ones that failed —
--     which `users` does not record. login_status is 'success',
--     or otp_missing / otp_expired / otp_wrong / otp_attempts_exceeded
--     when verification is switched on.
-- ------------------------------------------------------------
select login_time,
       mobile_number,
       login_status,
       platform,
       device_information
from login_history
order by login_time desc
limit 50;


-- ------------------------------------------------------------
--  3. One person's history
--     Put their number in E.164 — the form the app stores.
--     98765 43210 and +91 98765 43210 are both +919876543210.
-- ------------------------------------------------------------
select login_time, login_status, platform, device_information
from login_history
where mobile_number = '+919876543210'
order by login_time desc
limit 50;


-- ------------------------------------------------------------
--  4. "I added them but the group never reached their phone"
--
--     THE useful one. A member is linked to a real person only once
--     somebody has signed in with that exact number. Until then the
--     row is a placeholder: the group looks perfectly healthy on the
--     phone that made it, and does not exist on theirs.
--
--     Anything marked NO ACCOUNT is the answer.
-- ------------------------------------------------------------
select g.name                                as group_name,
       m.name                                as member_name,
       m.phone_e164,
       case when m.user_id is null
            then 'NO ACCOUNT'
            else 'ok' end                    as status
from group_members m
join groups g on g.id = m.group_id
where m.deleted = false
  and g.deleted = false
-- problems first: ordering on the text would put 'NO ACCOUNT' last,
-- because in ASCII lowercase 'ok' sorts above uppercase.
order by (m.user_id is null) desc, g.name;


-- ------------------------------------------------------------
--  5. Which build is everyone on
--     Half of any sync complaint. An old build on one phone
--     explains most "it works for me but not for him".
-- ------------------------------------------------------------
select coalesce(app_version, '(never reported)') as build,
       count(*)                                  as people,
       max(last_seen_at)                         as most_recent
from users
group by 1
order by 2 desc;


-- ------------------------------------------------------------
--  6. Every group, who created it, and how big it is
--     created_by is the only thing that decides who may delete a
--     group for everybody.
-- ------------------------------------------------------------
select g.name,
       u.name                                                as created_by,
       (select count(*) from group_members m
         where m.group_id = g.id and m.deleted = false)       as members,
       (select count(*) from expenses e
         where e.group_id = g.id and e.deleted = false)       as expenses,
       g.deleted                                             as deleted_for_everyone,
       g.created_at
from groups g
left join users u on u.id = g.created_by
order by g.created_at desc;


-- ------------------------------------------------------------
--  7. Who has removed a group from their own view
--     A member removing a group does not touch the group. This is
--     the per-account record of it, and nobody else is ever shown it.
-- ------------------------------------------------------------
select u.name  as person,
       u.mobile_number,
       g.name  as group_name,
       h.hidden_at
from group_hidden h
join users  u on u.id = h.user_id
join groups g on g.id = h.group_id
order by h.hidden_at desc;


-- ------------------------------------------------------------
--  8. Accounts that have gone quiet
--     Dormant is not a problem — nothing deactivates anybody
--     automatically. This is just so you can see it.
-- ------------------------------------------------------------
select name, mobile_number, app_version, last_seen_at,
       now() - last_seen_at as idle_for
from users
where last_seen_at is null
   or last_seen_at < now() - interval '30 days'
order by last_seen_at nulls first;


-- ------------------------------------------------------------
--  9. What is actually in the database
--     A quick sanity check after a deploy, and a rough size.
-- ------------------------------------------------------------
select 'users'         as table_name, count(*) from users
union all select 'groups',            count(*) from groups
union all select 'group_members',     count(*) from group_members
union all select 'group_hidden',      count(*) from group_hidden
union all select 'expenses',          count(*) from expenses
union all select 'settlements',       count(*) from settlements
union all select 'login_history',     count(*) from login_history
union all select 'sessions',          count(*) from sessions;


-- ------------------------------------------------------------
-- 10. One group's expenses, in rupees
--     Amounts are stored as integer paise so nothing is ever lost
--     to floating point — divide by 100 to read them.
--     Who owes what is computed in the app, not here: the split is
--     held as JSON, and re-implementing that maths in SQL would be
--     a second source of truth waiting to disagree with the first.
-- ------------------------------------------------------------
select e.expense_date,
       e.description,
       e.amount_minor / 100.0 as amount,
       e.category,
       e.split_type
from expenses e
join groups g on g.id = e.group_id
where g.name = 'Goa Trip'
  and e.deleted = false
order by e.expense_date desc;


-- ============================================================
--  WRITES — everything below CHANGES data. Read it first.
-- ============================================================

-- Deactivate an account. Every request from it is then refused with
-- 403, and its sessions stop working. Nothing else is touched: their
-- groups, expenses and balances stay exactly as they are.
--
-- update users set account_status = 'disabled'
-- where mobile_number = '+919876543210';

-- And back again.
--
-- update users set account_status = 'active'
-- where mobile_number = '+919876543210';

-- Sign someone out of every device without disabling them. They sign
-- in again as normal; nothing is lost.
--
-- update sessions set revoked_at = now()
-- where user_id = (select id from users where mobile_number = '+919876543210')
--   and revoked_at is null;

-- There is deliberately no "delete a user" here. Accounts are what
-- every group member row, expense and session points at, so removing
-- one by hand would strand the lot. If an account really has to go,
-- ask for it to be done properly in code, with the rows it owns
-- handled rather than orphaned.

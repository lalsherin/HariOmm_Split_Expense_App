"""Invite endpoints, plus the two public pages a shared link needs.

  POST /invites           make a link for a group you are in
  POST /invites/preview   what a link opens, before joining
  POST /invites/accept    join (signed in, after tapping Join)
  POST /invites/revoke    owner only: every link for the group stops working

  GET  /join/{token}                 the page a link opens in a browser
  GET  /.well-known/assetlinks.json  lets Android open /join links in the app
"""
import html
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..deps import current_user
from ..middleware.rate_limit import enforce
from ..models import User
from . import service

router = APIRouter(tags=["invites"])
settings = get_settings()


class GroupRef(BaseModel):
    group_id: str = Field(min_length=1, max_length=64)


class TokenRef(BaseModel):
    token: str = Field(min_length=1, max_length=128)


async def _limit(db: AsyncSession, user: User) -> None:
    await enforce(db, f"invite:{user.id}", settings.rl_invite_per_user,
                  settings.rl_invite_per_user_window)


def _raise(e: service.InviteError):
    raise HTTPException(e.status_code, e.message)


@router.post("/invites")
async def create_invite(body: GroupRef, user: User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)):
    await _limit(db, user)
    try:
        token, row = await service.create(db, user, body.group_id)
    except service.InviteError as e:
        await db.commit()
        _raise(e)
    await db.commit()
    return {"success": True, "token": token, "path": "/join/" + token,
            "expires_at": row.expires_at.isoformat(), "days": settings.invite_days}


@router.post("/invites/preview")
async def preview_invite(body: TokenRef, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    await _limit(db, user)
    out = await service.preview(db, user, body.token)
    await db.commit()
    return {"success": True, **out}


@router.post("/invites/accept")
async def accept_invite(body: TokenRef, user: User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)):
    await _limit(db, user)
    out = await service.accept(db, user, body.token)
    await db.commit()
    return {"success": True, **out}


@router.post("/invites/revoke")
async def revoke_invites(body: GroupRef, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    try:
        n = await service.revoke_all(db, user, body.group_id)
    except service.InviteError as e:
        _raise(e)
    await db.commit()
    return {"success": True, "revoked": n}


# ------------------------------------------------------------- public pages

@router.get("/.well-known/assetlinks.json", include_in_schema=False)
async def assetlinks():
    """Android checks this at install time; if it matches the app's signing
    certificate, tapping a /join link opens Split Buddy directly."""
    return JSONResponse([{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {"namespace": "android_app", "package_name": settings.android_package,
                   # comma-separated: the sideload key, plus Google's app-signing
                   # key once the app is on Play (Play re-signs what it ships)
                   "sha256_cert_fingerprints": [f.strip() for f in settings.android_cert_sha256.split(",") if f.strip()]},
    }])


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{title}</title>
<style>
:root {{ color-scheme: light dark; --bg:#eef0f4; --card:#fff; --ink:#141822; --muted:#7b8497; --accent:#1b4fa0; --line:#dde1e9; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0b0d12; --card:#161a21; --ink:#e8ebf1; --muted:#8b93a5; --accent:#6ea2f0; --line:#262c36; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
main {{ max-width:440px; margin:0 auto; padding:40px 18px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:26px 22px; text-align:center; }}
h1 {{ font-size:21px; margin:6px 0 8px; }}
p {{ color:var(--muted); margin:0 0 14px; }}
.btn {{ display:block; text-decoration:none; background:var(--accent); color:#fff; font-weight:600; padding:13px 16px; border-radius:12px; margin:18px 0 10px; }}
.small {{ font-size:13.5px; }}
.brand {{ font-weight:700; letter-spacing:-.01em; color:var(--accent); }}
ol {{ text-align:left; color:var(--muted); font-size:14px; padding-left:20px; margin:10px 0 0; }}
</style></head>
<body><main><div class="card">
<div class="brand">Split Buddy</div>
{body}
</div></main></body></html>"""


@router.get("/join/{token}", response_class=HTMLResponse, include_in_schema=False)
async def join_page(token: str, db: AsyncSession = Depends(get_db)):
    """Where a link lands when the app does not open it by itself: no app
    installed, or Android has not verified the link for this app yet. Shows the
    group's name and nothing else about it."""
    status, inv, group = await service.resolve(db, token)
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    if status != "ok":
        body = (f"<h1>Invite not available</h1><p>{html.escape(service.MESSAGES[status], quote=False)}</p>")
        return HTMLResponse(_PAGE.format(title="Split Buddy invite", body=body),
                            status_code=404 if status == "invalid" else 410, headers=headers)
    name = html.escape(group.name)
    here = f"/join/{token}"
    # Android: open the app if installed; if not, Chrome comes back to this
    # page with #install, which shows how to get it.
    intent = (f"intent://join/{quote(token)}#Intent;scheme=splitbuddy;"
              f"package={settings.android_package};"
              f"S.browser_fallback_url={quote(here + '#install', safe='')};end")
    get = (f'<a class="btn" style="background:none;color:var(--accent);border:1px solid var(--line)" '
           f'href="{html.escape(settings.app_download_url)}">Download Split Buddy</a>'
           if settings.app_download_url else
           "<p class=\"small\">Split Buddy isn't in an app store yet — ask the person who "
           "sent you this link for the app.</p>")
    body = f"""<h1>Join “{name}”</h1>
<p>You've been invited to share expenses in this group on Split Buddy.</p>
<a class="btn" href="{html.escape(intent)}">Open in Split Buddy</a>
<div id="install">
<p class="small">Don't have the app yet?</p>
{get}
<ol><li>Install Split Buddy and sign in with your mobile number.</li>
<li>Come back to this message and tap the link again.</li>
<li>Tap <b>Join group</b>.</li></ol>
</div>"""
    return HTMLResponse(_PAGE.format(title=f"Join {name} on Split Buddy", body=body), headers=headers)

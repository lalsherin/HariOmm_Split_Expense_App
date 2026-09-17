import pytest

pytestmark = pytest.mark.asyncio


async def test_first_sign_in_creates_the_account(phone):
    p = phone("9876543210", "Sherin")
    body = await p.sign_in()
    assert body["created"] is True
    assert body["user"]["mobile_number"] == "+919876543210"
    assert body["user"]["name"] == "Sherin"
    assert body["user"]["mobile_verified"] is False        # no OTP on this server


async def test_second_sign_in_finds_the_same_account(phone):
    a = phone("9876543210", "Sherin")
    first = await a.sign_in()
    b = phone("+91 98765 43210", "Sherin")                  # different spelling
    second = await b.sign_in()
    assert second["created"] is False
    assert second["user"]["id"] == first["user"]["id"]


async def test_name_can_be_corrected_on_a_later_sign_in(phone, client):
    p = phone("9876543210", "Sherin")
    await p.sign_in()
    p.name = "Sherin Lal"
    await p.sign_in()
    r = await client.get("/auth/me", headers=p.headers)
    assert r.json()["name"] == "Sherin Lal"


async def test_a_bad_number_is_refused(client):
    r = await client.post("/auth/sign-in", json={"mobile_number": "nope", "name": "X"})
    assert r.status_code == 400
    assert "recognise" in r.json()["message"]


async def test_me_needs_a_token(client):
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.get("/auth/me", headers={"Authorization": "Bearer nonsense"})
            ).status_code == 401


async def test_refresh_rotates_the_token(phone, client):
    p = phone("9876543210", "Sherin")
    await p.sign_in()
    old_refresh = p.refresh

    r = await client.post("/auth/refresh-token", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    new_access = r.json()["access_token"]
    assert r.json()["refresh_token"] != old_refresh
    assert (await client.get("/auth/me",
            headers={"Authorization": f"Bearer {new_access}"})).status_code == 200


async def test_a_dropped_reply_is_retried_not_punished(phone, client):
    """The phone gives up after 20 seconds; a sleeping instance can take 60 to
    wake. So a refresh is often processed here after the phone has walked away,
    leaving it holding a token this server thinks is spent. Repeating it
    promptly means "I never heard you", not "I stole this"."""
    p = phone("9876543210", "Sherin")
    await p.sign_in()
    token = p.refresh

    first = await client.post("/auth/refresh-token", json={"refresh_token": token})
    assert first.status_code == 200
    live_access = first.json()["access_token"]

    # the phone never saw that reply, so it tries again with what it still has
    again = await client.post("/auth/refresh-token", json={"refresh_token": token})
    assert again.status_code == 200, "a dropped reply must be recoverable"

    retry_access = again.json()["access_token"]
    assert (await client.get("/auth/me",
            headers={"Authorization": f"Bearer {retry_access}"})).status_code == 200
    # and nothing else was torn down on the way
    assert (await client.get("/auth/me",
            headers={"Authorization": f"Bearer {live_access}"})).status_code == 200


async def test_replay_after_the_grace_window_kills_every_session(phone, client, monkeypatch):
    """Outside the window a spent token is treated as copied: drop every
    session rather than leave the thief holding a live one."""
    from app.auth import router as auth_router
    monkeypatch.setattr(auth_router.settings, "refresh_grace_seconds", 0)

    p = phone("9876543210", "Sherin")
    await p.sign_in()
    stolen = p.refresh

    r = await client.post("/auth/refresh-token", json={"refresh_token": stolen})
    live_access = r.json()["access_token"]
    assert (await client.get("/auth/me",
            headers={"Authorization": f"Bearer {live_access}"})).status_code == 200

    replay = await client.post("/auth/refresh-token", json={"refresh_token": stolen})
    assert replay.status_code == 401

    assert (await client.get("/auth/me",
            headers={"Authorization": f"Bearer {live_access}"})).status_code == 401


async def test_the_grace_window_does_not_resurrect_a_dead_account(phone, client):
    """Signing out inside the grace window must stay signed out."""
    p = phone("9876543210", "Sherin")
    await p.sign_in()
    token = p.refresh
    assert (await client.post("/auth/logout", headers=p.headers)).status_code == 200
    # logout revoked the session; the refresh token belonging to it is spent,
    # and reusing it must not hand back a working session
    r = await client.post("/auth/refresh-token", json={"refresh_token": token})
    if r.status_code == 200:
        access = r.json()["access_token"]
        assert (await client.get("/auth/me",
                headers={"Authorization": f"Bearer {access}"})).status_code == 401, \
            "a signed-out session must not come back through the grace window"


async def test_logout_invalidates_the_token(phone, client):
    p = phone("9876543210", "Sherin")
    await p.sign_in()
    assert (await client.get("/auth/me", headers=p.headers)).status_code == 200
    assert (await client.post("/auth/logout", headers=p.headers)).status_code == 200
    assert (await client.get("/auth/me", headers=p.headers)).status_code == 401


async def test_logins_are_recorded(phone, client):
    p = phone("9876543210", "Sherin")
    await p.sign_in(platform="android", device_information="Redmi Note 12")
    r = await client.get("/users/me/logins", headers=p.headers)
    logins = r.json()["logins"]
    assert logins and logins[0]["login_status"] == "success"
    assert logins[0]["platform"] == "android"


async def test_rate_limit_stops_a_flood(client):
    from app.auth import router as auth_router
    original = auth_router.settings.rl_auth_per_number
    auth_router.settings.rl_auth_per_number = 3
    try:
        codes = []
        for _ in range(5):
            r = await client.post("/auth/sign-in",
                                  json={"mobile_number": "9876543299", "name": "Flood"})
            codes.append(r.status_code)
        assert 429 in codes, codes
        assert codes.count(200) <= 3
    finally:
        auth_router.settings.rl_auth_per_number = original


async def test_otp_flow_when_verification_is_switched_on(client):
    """The OTP machinery is dormant, not absent: flip REQUIRE_OTP and it works."""
    from app.auth import router as auth_router
    auth_router.settings.require_otp = True
    try:
        # no code -> refused
        r = await client.post("/auth/sign-in",
                              json={"mobile_number": "9876500001", "name": "Anu"})
        assert r.status_code == 400

        r = await client.post("/auth/request-otp", json={"mobile_number": "9876500001"})
        assert r.status_code == 200 and r.json()["otp_required"] is True
        code = r.json()["dev_otp"]                      # console provider echoes it
        assert len(code) == auth_router.settings.otp_length and code.isdigit()

        # wrong code -> refused
        wrong = "0000" if code != "0000" else "1111"
        assert (await client.post("/auth/sign-in", json={
            "mobile_number": "9876500001", "name": "Anu", "otp": wrong})).status_code == 400

        # right code -> in, and marked verified
        r = await client.post("/auth/sign-in", json={
            "mobile_number": "9876500001", "name": "Anu", "otp": code})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["mobile_verified"] is True

        # one-time use: the same code cannot be replayed
        assert (await client.post("/auth/sign-in", json={
            "mobile_number": "9876500001", "name": "Anu", "otp": code})).status_code == 400
    finally:
        auth_router.settings.require_otp = False


async def test_otp_resend_has_a_cooldown(client):
    from app.auth import router as auth_router
    auth_router.settings.require_otp = True
    try:
        assert (await client.post("/auth/request-otp",
                json={"mobile_number": "9876500002"})).status_code == 200
        second = await client.post("/auth/request-otp",
                                   json={"mobile_number": "9876500002"})
        assert second.status_code == 429
    finally:
        auth_router.settings.require_otp = False

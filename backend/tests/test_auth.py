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


async def test_refresh_rotates_and_burns_the_old_token(phone, client):
    p = phone("9876543210", "Sherin")
    await p.sign_in()
    old_refresh = p.refresh

    r = await client.post("/auth/refresh-token", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    new_access = r.json()["access_token"]
    assert r.json()["refresh_token"] != old_refresh
    assert (await client.get("/auth/me",
            headers={"Authorization": f"Bearer {new_access}"})).status_code == 200

    # the spent token must not work twice
    assert (await client.post("/auth/refresh-token",
            json={"refresh_token": old_refresh})).status_code == 401


async def test_replaying_a_spent_refresh_token_kills_every_session(phone, client):
    """If a spent token comes back, it was copied. Drop all of that user's
    sessions rather than leaving the thief with a live one."""
    p = phone("9876543210", "Sherin")
    await p.sign_in()
    stolen = p.refresh

    r = await client.post("/auth/refresh-token", json={"refresh_token": stolen})
    live_access = r.json()["access_token"]
    assert (await client.get("/auth/me",
            headers={"Authorization": f"Bearer {live_access}"})).status_code == 200

    await client.post("/auth/refresh-token", json={"refresh_token": stolen})  # replay

    assert (await client.get("/auth/me",
            headers={"Authorization": f"Bearer {live_access}"})).status_code == 401


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

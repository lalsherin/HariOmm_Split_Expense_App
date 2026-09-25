"""Two-phone harness (see run.sh): drives the real phone build against a real local backend.

The page is the APK's own assets/index.html with one line added (make_page.py)
so the test can reach functions inside the app's closure. Toasts are recorded
from the DOM, so every toast the person would have seen is counted.
"""
from playwright.async_api import async_playwright  # noqa: F401

import os
APP = "http://127.0.0.1:8080/" + os.environ.get("PAGE", "index.html")
SERVER = "http://127.0.0.1:8000"


class Phone:
    def __init__(self, ctx, page, name, mobile):
        self.ctx, self.page, self.name, self.mobile = ctx, page, name, mobile
        self.syncs = 0
        self.rejected = 0

    @classmethod
    async def open(cls, browser, name, mobile):
        ctx = await browser.new_context(viewport={"width": 412, "height": 915})
        await ctx.add_init_script(
            f"try {{ localStorage.setItem('sl.server', JSON.stringify('{SERVER}')); }} catch(e) {{}}")
        page = await ctx.new_page()
        p = cls(ctx, page, name, mobile)
        page.on("request", p._on_request)
        page.on("response", p._on_response)
        await page.goto(APP)
        r = await p.app("([m, n]) => signIn(m, n)", [mobile, name])
        assert r.get("ok"), r
        await p.reload()
        return p

    def _on_request(self, r):
        if r.url.endswith("/sync") and r.method == "POST":
            self.syncs += 1

    async def _on_response(self, r):
        if r.url.endswith("/sync") and r.request.method == "POST":
            try:
                self.rejected += len((await r.json()).get("rejected") or [])
            except Exception:
                pass

    async def app(self, fn_src, arg=None):
        """Run `fn_src` (a JS function) inside the app's closure."""
        import asyncio
        return await asyncio.wait_for(self.page.evaluate(
            "([src, arg]) => window.__t('(' + src + ')')(arg)", [fn_src, arg]), 30)

    async def reload(self):
        await self.page.reload()
        await self.page.wait_for_timeout(800)
        await self.page.evaluate("""() => {
          window.__toasts = [];
          const t = document.getElementById("toast");
          new MutationObserver(() => window.__toasts.push({t: Date.now(), m: t.textContent}))
            .observe(t, {childList: true, characterData: true, subtree: true});
        }""")

    async def toasts(self, needle="refused"):
        return [t for t in await self.page.evaluate("window.__toasts") if needle in t["m"]]

    async def sync(self):
        return await self.app("() => syncNow(true)")

    async def create_group(self, name, others):
        return await self.app("""([name, others]) => {
          const me = myIdentity();
          const g = { id: uid("g"), name, currency: "INR", createdAt: nowISO(), ownerId: myUserId(), members: [] };
          const row = { id: uid("m"), name: me.name, phone: me.mobile, updatedAt: nowISO() };
          g.members.push(row); LS.set(meKey(g.id), row.id);
          others.forEach(([n, p]) => g.members.push({ id: uid("m"), name: n, phone: p, updatedAt: nowISO() }));
          saveGroup(g); selectGroup(g.id);
          return g.id;
        }""", [name, others])

    async def live(self):
        return await self.app("() => liveGroups().map(g => g.name)")

    async def delete_for_everyone(self, gid):
        await self.app("gid => removeGroup(gid)", gid)

    async def hide(self, gid):
        await self.app("gid => hideGroup(gid)", gid)

    async def remove_member(self, gid, phone):
        await self.app("""([gid, phone]) => {
          const g = S.groups.find(x => x.id === gid);
          const m = g.members.find(x => x.phone === phone);
          m.deleted = true; m.updatedAt = nowISO(); saveGroup(g);
        }""", [gid, phone])

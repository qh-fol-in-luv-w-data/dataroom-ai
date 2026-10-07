"""scripts/sp_upload.py against an HTTP fake of Graph (no tenant needed)."""
import importlib.util
import json
from urllib.parse import parse_qs, unquote

import httpx

from dr.tenant.service import FakeTenant
from tests.mini_tenant import make_tenant


def load_script():
    spec = importlib.util.spec_from_file_location("sp_upload", "scripts/sp_upload.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeSP:
    def __init__(self):
        self.columns, self.files, self.fields, self.puts = [], {}, {}, 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = unquote(req.url.path)
        if req.url.host == "login.microsoftonline.com":
            form = parse_qs(req.content.decode())
            assert form["grant_type"] == ["refresh_token"]
            return httpx.Response(200, json={"access_token": "user-token", "refresh_token": "r2", "expires_in": 3600})
        assert req.headers["authorization"] == "Bearer user-token"
        p = path.removeprefix("/v1.0/")
        if p == "sites/contoso.sharepoint.com:/sites/demo":
            return httpx.Response(200, json={"id": "S"})
        if p == "sites/S/drive":
            return httpx.Response(200, json={"id": "D"})
        if p == "sites/S/drive/list":
            return httpx.Response(200, json={"id": "L"})
        if p == "sites/S/lists/L/columns":
            if req.method == "POST":
                self.columns.append(json.loads(req.content))
                return httpx.Response(201, json={})
            return httpx.Response(200, json={"value": [{"name": c["name"]} for c in self.columns]})
        if p.startswith("drives/D/root:/") and p.endswith(":/content"):
            rel = p[len("drives/D/root:/"):-len(":/content")]
            self.puts += 1
            self.files[rel] = req.content
            return httpx.Response(201, json={"id": rel, "webUrl": f"https://contoso.sharepoint.com/sites/demo/{rel}"})
        if p.startswith("drives/D/items/") and p.endswith("/listItem/fields"):
            self.fields[p.split("/")[3]] = json.loads(req.content)
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"error": p})


def test_upload_and_links(tmp_path, monkeypatch):
    mod = load_script()
    ten = make_tenant(tmp_path / "tenant")
    t = json.loads((ten / "tenant.json").read_text())
    t["items"][0]["malware"] = True                       # never uploaded
    (ten / "tenant.json").write_text(json.dumps(t, ensure_ascii=False))
    monkeypatch.setattr(mod, "TEN", ten)
    monkeypatch.setattr(mod, "LINKS", ten / "sharepoint_links.json")
    cache = tmp_path / "token.json"
    cache.write_text(json.dumps({"client_id": "app", "refresh_token": "r1"}))
    monkeypatch.setattr(mod, "CACHE", cache)
    monkeypatch.setattr(mod.DeviceLogin.__init__, "__defaults__", (cache,))
    fake = FakeSP()
    http = httpx.Client(transport=httpx.MockTransport(fake))
    args = ["--tenant", "contoso.onmicrosoft.com", "--client-id", "app", "--site", "https://contoso.sharepoint.com/sites/demo"]
    assert mod.main(args, http=http) == 0
    n = len(t["items"]) - 1
    assert fake.puts == n and fake.columns[0]["choice"]["choices"] == ["Allowed", "OnPremOnly", "Excluded"]
    assert t["items"][0]["name"] not in "".join(fake.files)
    assert all(v["AI_Use"] in ("Allowed", "OnPremOnly", "Excluded") for v in fake.fields.values())
    links = json.loads((ten / "sharepoint_links.json").read_text())
    assert len(links) == n and json.loads(cache.read_text())["refresh_token"] == "r2"
    # a re-run uploads nothing new and does not create the column twice
    assert mod.main(args, http=http) == 0 and fake.puts == n and len(fake.columns) == 1
    # the demo tenant now cites the real SharePoint copy
    tenant = FakeTenant(ten)
    some = next(iter(links))
    assert tenant.web_url(some).startswith("https://contoso.sharepoint.com/sites/demo/")

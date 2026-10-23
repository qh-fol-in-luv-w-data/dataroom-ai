"""Download a whole SharePoint folder (recursively) through a real browser session.

Opens Chromium with a persistent profile; you sign in by hand the first time
(MFA included). The script then walks the folder with the SharePoint REST API
using the browser's own cookies and saves every file, keeping the folder tree.
Re-running skips files that are already on disk with the same size.

    python scripts/sp_download.py "<SharePoint folder URL>" [--out DIR]
"""
import argparse
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests
from playwright.sync_api import sync_playwright

PROFILE = Path("data/cache/sp_profile")
JSON = {"Accept": "application/json;odata=nometadata"}


def parse_target(url):
    u = urlparse(url)
    folder = parse_qs(u.query).get("id", [None])[0]
    if not folder:
        sys.exit("URL has no ?id=<folder path>; open the folder in SharePoint and copy the URL")
    parts = folder.strip("/").split("/")
    site = f"{u.scheme}://{u.netloc}/{parts[0]}/{parts[1]}"  # /sites/<name>
    library = "/" + "/".join(parts[:3])  # /sites/<name>/<document library>
    return site, library, folder


def wait_for_login(page, ctx, site):
    print("Đăng nhập trong cửa sổ Chromium nếu được hỏi ... (chờ tối đa 10 phút)")
    deadline = time.time() + 600
    while time.time() < deadline:
        r = ctx.request.get(f"{site}/_api/web/title", headers=JSON, fail_on_status_code=False)
        if r.ok:
            print("Đã đăng nhập:", r.json().get("value"))
            return
        page.wait_for_timeout(3000)
    sys.exit("Hết thời gian chờ đăng nhập")


def fetch(ctx, url, tries=8, method="GET", **kw):
    """Request with retries: the connection drops (DNS, resets, 429/503 throttling) on long runs."""
    for i in range(tries):
        try:
            r = ctx.request.fetch(url, method=method, fail_on_status_code=False, **kw)
            if r.status not in (429, 500, 502, 503, 504):
                return r
            err = f"HTTP {r.status}"
        except Exception as e:
            err = str(e).splitlines()[0]
        wait = min(5 * 2 ** i, 120)
        print(f"  thử lại sau {wait}s ({err})")
        time.sleep(wait)
    raise RuntimeError(f"hết lượt thử: {err}")


VIEW = ("<View Scope='RecursiveAll'><Query/><ViewFields><FieldRef Name='ID'/><FieldRef Name='FileRef'/>"
        "<FieldRef Name='FSObjType'/><FieldRef Name='File_x0020_Size'/><FieldRef Name='SMTotalFileStreamSize'/>"
        "<FieldRef Name='PermMask'/></ViewFields>"
        "<RowLimit Paged='TRUE'>5000</RowLimit></View>")


OPEN_ITEMS = 0x20  # SPBasePermissions.OpenItems: without it ("view only") the file body can't be fetched


def file_size(row):
    return int(row.get("File_x0020_Size") or row.get("SMTotalFileStreamSize") or 0)


def can_open(row):
    return bool(int(row.get("PermMask") or "0x0", 16) & OPEN_ITEMS)


def list_files(ctx, site, library, folder):
    """Every file under `folder`, recursively. RenderListDataAsStream takes the folder in a POST
    body, so deep paths never hit SharePoint's maxUrlLength, and it pages past the 5000-item view limit."""
    digest = fetch(ctx, f"{site}/_api/contextinfo", method="POST", headers=JSON).json()["FormDigestValue"]
    endpoint = f"{site}/_api/web/GetList(@l)/RenderListDataAsStream?@l='{quote(library.replace(chr(39), chr(39) * 2))}'"
    body = {"parameters": {"RenderOptions": 2, "ViewXml": VIEW, "FolderServerRelativeUrl": folder}}
    url, files = endpoint, []
    while url:
        r = fetch(ctx, url, method="POST", headers={**JSON, "Content-Type": "application/json", "X-RequestDigest": digest},
                  data=json.dumps(body))
        if not r.ok:
            raise RuntimeError(f"{r.status}\n{r.text()[:300]}")
        d = r.json()
        files += [row for row in d.get("Row", []) if str(row.get("FSObjType")) == "0"]
        nxt = d.get("NextHref")
        url = f"{endpoint}&{nxt.lstrip('?')}" if nxt else None
        print(f"  đã liệt kê {len(files)} file ...")
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default="data/sp_download")
    ap.add_argument("--max-gb", type=float, default=None,
                    help="stop after downloading this much; smallest files go first so the budget covers the most files")
    ap.add_argument("--workers", type=int, default=4, help="parallel downloads")
    ap.add_argument("--min-free-gb", type=float, default=4, help="stop when the disk has less free space than this")
    args = ap.parse_args()

    site, library, folder = parse_target(args.url)
    out_root = Path(args.out) / folder.rstrip("/").split("/")[-1]
    PROFILE.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False, accept_downloads=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(args.url)
        wait_for_login(page, ctx, site)

        try:
            files = list_files(ctx, site, library, folder)
        except RuntimeError as e:
            sys.exit(f"Không liệt kê được thư mục: {e}")
        print(f"Tìm thấy {len(files)} file ({sum(map(file_size, files)) / 1e9:.1f} GB)")
        cookies = {c["name"]: c["value"] for c in ctx.cookies(site)}
        user_agent = page.evaluate("navigator.userAgent")
        ctx.close()

    if args.max_gb:  # smallest first, so the budget covers as many files as possible
        files.sort(key=file_size)
    budget = args.max_gb * 1e9 if args.max_gb else float("inf")
    manifest, todo, planned, skipped, no_access = [], [], 0, 0, 0
    for f in files:
        rel = f["FileRef"][len(folder):].lstrip("/")
        size = file_size(f)
        manifest.append({"path": rel, "size": size, "url": f["FileRef"], "can_download": can_open(f)})
        dest = out_root / rel
        if not can_open(f):
            no_access += 1
        elif dest.exists() and dest.stat().st_size == size:
            skipped += 1
        elif planned + size <= budget:
            todo.append((f, rel, dest, size))
            planned += size
    print(f"Sẽ tải {len(todo)} file ({planned / 1e9:.1f} GB), bỏ qua {skipped} file đã có, "
          f"{no_access} file chỉ có quyền xem (không tải được)")

    # The browser session's cookies work for plain HTTP, which lets downloads run in parallel.
    sess = requests.Session()
    sess.cookies.update(cookies)
    sess.headers["User-Agent"] = user_agent
    sess.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=args.workers))
    lib_arg = quote(library.replace("'", "''"))
    lock, stop = threading.Lock(), threading.Event()
    stats = {"done": 0, "bytes": 0}
    throttled_until = [0.0]  # shared by all workers: one throttle response pauses everyone
    failed = []

    def download(item):
        f, rel, dest, size = item
        if stop.is_set():
            return
        if shutil.disk_usage(out_root.parent if out_root.parent.exists() else ".").free < args.min_free_gb * 1e9:
            stop.set()
            print("Ổ đĩa sắp đầy, dừng.")
            return
        # by item id first (short URL), then by path. Redirects are not followed: SharePoint answers
        # throttling and "request access" with a 302 to an HTML page that must never be saved as the file.
        urls = [f"{site}/_api/web/GetList(@l)/items({f['ID']})/File/$value?@l='{lib_arg}'",
                f"{site}/_api/web/GetFileByServerRelativePath(decodedurl='{quote(f['FileRef'].replace(chr(39), chr(39) * 2))}')/$value"]
        err = None
        for url in urls:
            for attempt in range(10):
                pause = throttled_until[0] - time.time()
                if pause > 0:
                    time.sleep(pause)
                try:
                    with sess.get(url, stream=True, timeout=(30, 300), allow_redirects=False) as r:
                        loc = r.headers.get("Location", "")
                        if r.status_code in (429, 503) or "Throttle" in loc:
                            wait = int(r.headers.get("Retry-After") or 0) or min(30 * 2 ** attempt, 600)
                            with lock:
                                if time.time() + wait > throttled_until[0]:
                                    throttled_until[0] = time.time() + wait
                                    print(f"  SharePoint giới hạn tốc độ, tạm dừng {wait}s")
                            raise RuntimeError("throttled")
                        if r.status_code in (500, 502, 504):
                            raise RuntimeError(f"HTTP {r.status_code}")
                        if not r.ok or r.is_redirect:
                            err = f"HTTP {r.status_code}"
                            break
                        if "text/html" in r.headers.get("Content-Type", "") and not rel.lower().endswith((".htm", ".html", ".aspx")):
                            err = "trả về trang HTML thay vì file"
                            break
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        part = dest.with_name(dest.name + ".part")
                        with open(part, "wb") as out:
                            for chunk in r.iter_content(1 << 20):
                                out.write(chunk)
                        part.replace(dest)
                    with lock:
                        stats["done"] += 1
                        stats["bytes"] += dest.stat().st_size
                        print(f"[{stats['done']}/{len(todo)}] {rel} ({dest.stat().st_size / 1e6:.1f} MB) "
                              f"- tổng {stats['bytes'] / 1e9:.2f} GB")
                    return
                except Exception as e:
                    err = str(e).splitlines()[0]
                    if err != "throttled":
                        time.sleep(min(5 * 2 ** attempt, 120))
        with lock:
            failed.append({"path": rel, "error": err})
            print(f"LỖI {rel}: {err}")

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(download, todo))

    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "_manifest.json").write_text(
        json.dumps({"source": args.url, "files": manifest, "failed": failed}, ensure_ascii=False, indent=1))
    print(f"\nXong: tải {stats['done']} file ({stats['bytes'] / 1e9:.2f} GB), bỏ qua {skipped} file đã có, lỗi {len(failed)}.")
    print("Thư mục:", out_root.resolve())

if __name__ == "__main__":
    main()

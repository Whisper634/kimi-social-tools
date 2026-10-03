"""bili.py — B站投稿/评论/置顶自动化（UPOS 直传，免官方上传组件）。

用法：
    python3 bili.py refresh-cookies          # 从 Chrome 抓 Cookie 存本地（过期时重跑）
    python3 bili.py publish <视频> --title "..." --desc "..." [--tag "a,b,c"]
    python3 bili.py comment <aid> --text "..." [--no-pin]

Cookie 存本目录 bili_cookies.json（chmod 600）。SESSDATA 约一个月过期，
调用返回 -101 时 refresh-cookies 重抓即可。

已固化的坑：
- UPOS 初始化用 POST 不是 PUT（PUT 被 411 拒，浏览器禁设 Content-Length）
- add/v3 的 filename 不带 .mp4 扩展名（带则 21015）
- 全程页面 XHR（fetch 被站点包装会失败）；分块上传不需要 withCredentials
- 评论置顶是 /x/v2/reply/top（不是 /top/add，那个 404）
- 审核中的稿件评论不可见但可提交，置顶等过审后生效
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wb import WB  # noqa: E402

HERE = Path(__file__).resolve().parent
COOKIES = HERE / "bili_cookies.json"
TID = 138  # 知识·人文社科
MID = "3706976546588731"


# ---------- Cookie ----------
def refresh_cookies():
    wb = WB()
    d = wb.cdp("Network.getAllCookies")
    cookies = d.get("cookies", [])
    bili = {c["name"]: c["value"] for c in cookies
            if c["domain"].endswith(".bilibili.com") or c["domain"] == "bilibili.com"}
    need = ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "buvid3", "buvid4", "b_nut"]
    keep = {k: v for k, v in bili.items() if k in need}
    if "SESSDATA" not in keep:
        raise RuntimeError("Chrome 里没有 B站 登录 Cookie，先在 Chrome 登录 bilibili.com")
    COOKIES.write_text(json.dumps(keep, indent=1))
    COOKIES.chmod(0o600)
    print(f"已存 {list(keep.keys())}")


def _load():
    if not COOKIES.exists():
        raise SystemExit("先运行: python3 bili.py refresh-cookies")
    return json.loads(COOKIES.read_text())


def _ck():
    c = _load()
    return "; ".join(f"{k}={v}" for k, v in c.items())


def _csrf():
    return _load().get("bili_jct", "")


def _http(method, url, body=None, referer="https://www.bilibili.com", raw=False):
    headers = {
        "Cookie": _ck(),
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/138.0 Safari/537.36",
        "Referer": referer,
    }
    data = None
    if body is not None:
        if raw:
            data = body.encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


# ---------- 投稿（UPOS） ----------
def _upos_js(video_path, up):
    """生成在 member.bilibili.com 页面上下文执行的 UPOS 上传 JS。"""
    import base64
    b64 = base64.b64encode(open(video_path, "rb").read()).decode()
    auth = up["auth"]
    base = "https:" + up["endpoint"].rstrip("/") + "/" + up["upos_uri"].replace("upos://", "", 1)
    size = Path(video_path).stat().st_size
    name = Path(video_path).name
    return f"""
    (async () => {{
      const AUTH = {json.dumps(auth)};
      const BASE = {json.dumps(base)};
      const SIZE = {size};
      const b64 = "{b64}";
      const bin = atob(b64);
      const u8 = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      const xhr = (m, url, body, headers) => new Promise((res, rej) => {{
        const x = new XMLHttpRequest();
        x.open(m, url, true);
        x.withCredentials = false;
        for (const [k,v] of Object.entries(headers||{{}})) x.setRequestHeader(k, v);
        x.onload = () => res(x.responseText);
        x.onerror = () => rej(m + ' err');
        x.send(body);
      }});
      const init = await xhr('POST', BASE + '?uploads&output=json', new Blob([]), {{'X-Upos-Auth': AUTH}});
      const uid = JSON.parse(init).upload_id;
      const chunkSize = {up['chunk_size']};
      const n = Math.ceil(SIZE / chunkSize);
      for (let i = 0; i < n; i++) {{
        const part = u8.slice(i*chunkSize, Math.min(SIZE, (i+1)*chunkSize));
        const start = i*chunkSize, end = start + part.length;
        await xhr('PUT', BASE + '?partNumber='+(i+1)+'&uploadId='+uid+'&chunk='+i+'&chunks='+n
          +'&size='+part.length+'&start='+start+'&end='+end+'&total='+SIZE+'&output=json',
          part, {{'X-Upos-Auth': AUTH, 'Content-Type': 'application/octet-stream'}});
      }}
      const fd = new FormData();
      fd.append('output','json'); fd.append('fileName', {json.dumps(name)});
      fd.append('fileSize', String(SIZE)); fd.append('md5','');
      fd.append('chunks', String(n)); fd.append('threads','5');
      const done = await xhr('POST', BASE + '?uploadId='+uid+'&output=json', fd, {{'X-Upos-Auth': AUTH}});
      const key = JSON.parse(done).key || '';
      return key.replace(/^\\//, '').replace(/\\.mp4$/, '');
    }})()
    """


def publish(video_path, title, desc, tag="社交,电子游戏,Z世代,青年文化"):
    size = Path(video_path).stat().st_size
    name = Path(video_path).name
    print("[1/3] preupload", flush=True)
    up = _http("POST",
               "https://member.bilibili.com/preupload?name=" + urllib.parse.quote(name)
               + f"&size={size}&r=upos&profile=ugcupos%2Fbup&ssl=0&version=2.8.9"
                 "&build=2080900&upcdn=bda2&probe_version=20221109&client=web",
               referer="https://member.bilibili.com/")
    if up.get("OK") != 1:
        raise RuntimeError(f"preupload 失败: {up}")
    print("[2/3] UPOS 上传", flush=True)
    wb = WB()
    wb.bring_to_front()
    wb.navigate("https://member.bilibili.com/york/videoup")
    time.sleep(5)
    filename = wb.evaluate(_upos_js(video_path, up), await_promise=True, timeout=600)
    print(f"  上传完成: {filename}", flush=True)
    print("[3/3] 注册稿件", flush=True)
    body = {
        "copyright": 1, "cover": "", "title": title, "tid": TID, "tag": tag,
        "desc": desc, "desc_format_id": 0, "dynamic": "",
        "videos": [{"filename": filename, "title": Path(video_path).stem, "desc": ""}],
        "dtime": 0, "open_elec": 0, "no_reprint": 0, "recreate": -1,
        "act_reserve_create": 0,
    }
    r = _http("POST",
              f"https://member.bilibili.com/x/vu/web/add/v3?web_location=333.1024&csrf={_csrf()}",
              body=json.dumps(body, ensure_ascii=False), raw=True,
              referer="https://member.bilibili.com/")
    d = r
    if d.get("code") != 0:
        raise RuntimeError(f"注册失败: {d}")
    print(f"✅ 投稿成功 aid={d['data']['aid']} bvid={d['data']['bvid']}（审核中）", flush=True)
    return d["data"]


# ---------- 评论 + 置顶 ----------
def comment(aid, text, pin=True):
    print(f"[comment] aid={aid}", flush=True)
    r = _http("POST", "https://api.bilibili.com/x/v2/reply/add",
              {"type": "1", "oid": aid, "message": text, "csrf": _csrf()})
    if r.get("code") != 0:
        raise RuntimeError(f"评论失败: {r}")
    rpid = r["data"]["rpid_str"]
    print(f"  评论成功 rpid={rpid}", flush=True)
    if pin:
        time.sleep(1)
        p = _http("POST", "https://api.bilibili.com/x/v2/reply/top",
                  {"oid": aid, "type": "1", "rpid": rpid, "action": "1", "csrf": _csrf()})
        if p.get("code") != 0:
            raise RuntimeError(f"置顶失败: {p}（稿件可能仍在审核，稍后重试）")
        print("  置顶成功", flush=True)


def ensure_pinned(aid):
    """核验aid下作者评论已置顶；未置顶则补置顶。返回 True 表示已置顶。"""
    r = _http("GET", f"https://api.bilibili.com/x/v2/reply?type=1&oid={aid}&sort=1&ps=10")
    data = r.get("data") or {}
    top = (data.get("upper") or {}).get("top")
    if top and str(top.get("mid")) == MID:
        return True
    mine = next((x for x in (data.get("replies") or []) if str(x.get("mid")) == MID), None)
    if not mine:
        return False
    p = _http("POST", "https://api.bilibili.com/x/v2/reply/top",
              {"oid": aid, "type": "1", "rpid": str(mine["rpid_str"]), "action": "1", "csrf": _csrf()})
    return p.get("code") == 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("refresh-cookies")
    p = sub.add_parser("publish")
    p.add_argument("video")
    p.add_argument("--title", required=True)
    p.add_argument("--desc", default="")
    p.add_argument("--tag", default="社交,电子游戏,Z世代,青年文化")
    c = sub.add_parser("comment")
    c.add_argument("aid")
    c.add_argument("--text", required=True)
    c.add_argument("--no-pin", action="store_true")
    e = sub.add_parser("ensure-pinned")
    e.add_argument("aid")
    a = ap.parse_args()
    if a.cmd == "refresh-cookies":
        refresh_cookies()
    elif a.cmd == "publish":
        publish(a.video, a.title, a.desc, a.tag)
    elif a.cmd == "comment":
        comment(a.aid, a.text, pin=not a.no_pin)
    elif a.cmd == "ensure-pinned":
        print("pinned" if ensure_pinned(a.aid) else "not yet")

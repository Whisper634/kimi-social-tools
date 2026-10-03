"""sms.py — 从 macOS「信息」读取最新短信验证码。

- 直接读 chat.db（只读），自动排除已使用过的码（防复用旧码）
- 支持抖音/B站/其他「验证码XXXX」格式

用法：
    python3 sms.py           # 打印最新未使用的验证码
    python3 sms.py --mark    # 取码并标记为已使用
"""
import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

DB = Path.home() / "Library/Messages/chat.db"
STATE = Path(__file__).resolve().parent / ".sms_used.json"
PATTERN = re.compile(r"验证码[：:]?\s*(\d{4,8})")


def load_used():
    if STATE.exists():
        try:
            return {tuple(x) for x in json.loads(STATE.read_text())}
        except Exception:
            return set()
    return set()


def save_used(used):
    STATE.write_text(json.dumps(sorted(used)[-200:]))


def latest(valid_minutes=6, mark=False):
    """返回 (code, time_str)；没有未使用的新码返回 (None, None)。"""
    used = load_used()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT datetime(m.date/1000000000 + 978307200, 'unixepoch', 'localtime'), m.text "
        "FROM message m WHERE m.text LIKE '%验证码%' ORDER BY m.date DESC LIMIT 20"
    ).fetchall()
    con.close()
    now = time.time()
    for ts_str, text in rows or []:
        try:
            t = time.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            ts = time.mktime(t)
        except Exception:
            continue
        if now - ts > valid_minutes * 60:
            continue
        m = PATTERN.search(text or "")
        if not m:
            continue
        code = m.group(1)
        if (code, ts_str) in used:
            continue
        if mark:
            used.add((code, ts_str))
            save_used(used)
        return code, ts_str
    return None, None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mark", action="store_true", help="取码并标记为已使用")
    ap.add_argument("--valid", type=int, default=6, help="码有效分钟数（默认6）")
    a = ap.parse_args()
    code, ts = latest(a.valid, a.mark)
    if code:
        print(code)
        if not a.mark:
            print(f"# {ts}（未标记，下次仍会返回；建议用 --mark 取码）", file=__import__("sys").stderr)
    else:
        print("NO_CODE", file=__import__("sys").stderr)
        raise SystemExit(1)

"""shots_lint.py — 分镜 JSON 静态检查（出片前拦截超宽/超高/超行数）。

血泪背景：EP2–EP4 有若干 72px 正文行右端被画布裁掉（如
「今晚你没在，明天你就听不懂；」句末分号只显示一半）——已发布，
无法撤回，只能重制。这个 lint 在写稿/渲染阶段就把这类错拦下。

检查项（依据 content-pipeline/visual.py 的版式常量）：
  ERROR（会出可见残次品，退出码 1）：
    - 任意文字行右缘 > 1070px（画布 1080，出血裁切）
    - data 大数字右缘 > 940（白卡边缘）
    - data_cap 折行 > 2 行（白卡 720→825 只放得下 2 行）
    - body/end 行数 > 6（会撞底部字幕条 1696）
    - 批注 > 24 字（竖排滑入区底 1660 / 字高 47.2）
    - 时间轴 start>=end 或与上一镜重叠
  WARN（不挡出片，但人工看一眼）：
    - 该镜有批注时正文行右缘 > 945（压到批注分隔线，重字会撞批注）

用法：
    python3 shots_lint.py fame/recordings/007-EP5/shots.json [更多.json ...]
退出码：0 = 无 ERROR（可有 WARN）；1 = 有 ERROR。
"""
import json
import sys
from pathlib import Path

PIPE = Path(__file__).resolve().parent.parent / "content-pipeline"
sys.path.insert(0, str(PIPE))
from visual import (BODY_FONT, CAP_FONT, MARGIN_X, NOTE_LINE_X, NUM_FONT,
                    SUB_FONT, TITLE_FONT, font, text_w, wrap_text)  # noqa: E402

CANVAS_W = 1080
EDGE_X = 1070                    # 文字右缘硬上限
CARD_RIGHT = 940                 # data 白卡右缘（数字起点 x=150）
DIVIDER_X = NOTE_LINE_X          # 批注分隔线
CAP_MAX_LINES = 2
NOTE_MAX_LEN = 24
BODY_MAX_LINES = 6


def lint_file(path):
    data = json.loads(Path(path).read_text())
    shots = data["shots"] if isinstance(data, dict) else data
    errs, warns = [], []
    prev_end = None
    for i, s in enumerate(shots):
        tag = f"shot{i}({s.get('kind')},{s.get('start')}s)"
        kind, lines = s.get("kind"), s.get("lines") or []
        note = s.get("note") or ""
        if not (s.get("start", 1) < s.get("end", 0)):
            errs.append(f"{tag}: start>=end")
        if prev_end is not None and s.get("start", 0) < prev_end - 1e-6:
            errs.append(f"{tag}: 与上一镜时间重叠 (prev_end={prev_end})")
        prev_end = s.get("end")

        def check(line, fnt, limit, what):
            w = text_w(fnt, line)
            if MARGIN_X + w > EDGE_X:
                errs.append(f"{tag}: {what}出血 {MARGIN_X + w:.0f}>{CANVAS_W}「{line}」")
            elif note and MARGIN_X + w > DIVIDER_X and what != "批注":
                warns.append(f"{tag}: {what}压批注线 {MARGIN_X + w:.0f}>{DIVIDER_X}「{line}」")

        if kind == "open":
            for ln in lines[:2]:
                check(ln, font(TITLE_FONT), None, "标题")
            for ln in lines[2:]:
                check(ln, font(SUB_FONT), None, "副题")
        elif kind in ("body", "end"):
            if len(lines) > BODY_MAX_LINES:
                errs.append(f"{tag}: {len(lines)} 行 > {BODY_MAX_LINES} 行上限")
            for ln in lines:
                check(ln, font(BODY_FONT), None, "正文")
        elif kind == "data":
            num = s.get("data_num") or ""
            if 150 + text_w(font(NUM_FONT), num) > CARD_RIGHT:
                errs.append(f"{tag}: 数字出卡 {150 + text_w(font(NUM_FONT), num):.0f}>{CARD_RIGHT}「{num}」")
            cap_lines = wrap_text(s.get("data_cap") or "", font(CAP_FONT), 700)
            if len(cap_lines) > CAP_MAX_LINES:
                errs.append(f"{tag}: data_cap {len(cap_lines)} 行 > {CAP_MAX_LINES}「{s.get('data_cap')}」")
            for ln in cap_lines:
                check(ln, font(CAP_FONT), None, "cap")
        else:
            errs.append(f"{tag}: 未知 kind")
        if len(note) > NOTE_MAX_LEN:
            errs.append(f"{tag}: 批注 {len(note)} 字 > {NOTE_MAX_LEN}「{note}」")
    return errs, warns


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    n_err = n_warn = 0
    for p in sys.argv[1:]:
        errs, warns = lint_file(p)
        name = Path(p).parent.name + "/" + Path(p).name
        n_err += len(errs)
        n_warn += len(warns)
        mark = "✗" if errs else ("△" if warns else "✓")
        print(f"{mark} {name} (ERR {len(errs)} / WARN {len(warns)})")
        for e in errs:
            print(f"    ✗ {e}")
        for w in warns:
            print(f"    △ {w}")
    print(f"\n合计：{n_err} ERROR，{n_warn} WARN")
    raise SystemExit(1 if n_err else 0)

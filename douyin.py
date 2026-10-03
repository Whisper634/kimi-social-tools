"""douyin.py — 抖音创作者平台自动化（发布作品 / 发评论），流程已六连验证。

用法：
    python3 douyin.py publish <视频路径> --title "..." --desc "..."
    python3 douyin.py comment <视频ID> --text "..."
    python3 douyin.py login        # 登录态掉了时自动短信登录

前置：
    - Chrome 装好 Kimi 扩展且能访问文件网址（chrome://extensions 开一次）
    - 本会话已 bring_to_front + focus_emulation（WB 自动处理）

已固化的坑（改流程前先读 RUNBOOK.md）：
    - 标题 30 字硬限制，超长会被静默截断 → 这里直接报错拒绝
    - 简介必须 execCommand insertText 进 contenteditable
    - 发布短信验证的「验证」是 div，必须 JS dispatchEvent，坐标点击会误中「取消」
    - 评论输入必须 CDP Input.insertText（execCommand 会弄崩 Draft 编辑器）
    - 评论发送图标 = #comment-input-container 里的 36x36 span(.wchsYBpK)
    - 成功标志：跳到 content/manage?enter_from=publish
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wb import WB, WBError  # noqa: E402
from sms import latest as sms_latest  # noqa: E402

TITLE_LIMIT = 30
UPLOAD = "https://creator.douyin.com/creator-micro/content/upload"
MANAGE = "https://creator.douyin.com/creator-micro/content/manage"


def _wait(wb, cond_js, timeout=90, every=3):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if wb.evaluate(cond_js):
            return True
        time.sleep(every)
    return False


def _sms_verify(wb):
    """处理 second-verify 短信面板；没有面板返回 False。"""
    panel = "!![...document.querySelectorAll('*')].find(e => e.children.length===0 && (e.textContent||'').includes('接收短信验证码'))"
    if not wb.evaluate(panel):
        return False
    print("  [sms] 出现短信验证面板", flush=True)
    wb.evaluate("""
      (() => { const g = [...document.querySelectorAll('*')].find(e => e.children.length===0
        && (e.textContent||'').trim()==='获取验证码' && e.offsetParent);
        if (g) (g.closest('[class*=button]')||g).click(); return !!g; })()
    """)
    time.sleep(12)
    code, _ = sms_latest(mark=True)
    if not code:
        raise WBError("收不到短信验证码")
    print(f"  [sms] 验证码 {code}", flush=True)
    r = wb.evaluate(f"""
      (() => {{
        const inp = [...document.querySelectorAll('input')].find(i => i.placeholder==='请输入验证码');
        if (!inp) return 'no input';
        const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
        s.call(inp, '{code}');
        inp.dispatchEvent(new Event('input',{{bubbles:true}}));
        inp.dispatchEvent(new Event('change',{{bubbles:true}}));
        const btn = [...document.querySelectorAll('div')].find(e => e.children.length===0
          && e.textContent.trim()==='验证' && e.offsetParent && e.className.includes('sms-verify'));
        if (!btn) return 'code filled, no verify btn';
        for (const t of ['mousedown','mouseup','click']) btn.dispatchEvent(new MouseEvent(t,{{bubbles:true}}));
        return 'verify clicked';
      }})()
    """)
    print(f"  [sms] {r}", flush=True)
    return True


def publish(video_path, title, desc):
    if len(title) > TITLE_LIMIT:
        raise WBError(f"标题 {len(title)} 字 > {TITLE_LIMIT} 字硬限制，请先精简")
    wb = WB()
    wb.bring_to_front()
    wb.focus_emulation(True)
    print("[1/6] 打开上传页", flush=True)
    wb.navigate(UPLOAD)
    time.sleep(8)
    if "login" in wb.current_url():
        raise WBError("登录态掉了，先运行: python3 douyin.py login")
    print("[2/6] 注入视频", flush=True)
    js = wb.file_to_b64_js(video_path) + wb.b64_to_uint8() + f"""
    (() => {{
      const f = new File([__u8], "{Path(video_path).stem}-dy.mp4", {{type:"video/mp4"}});
      const dt = new DataTransfer(); dt.items.add(f);
      for (const t of [document, document.body]) {{
        t.dispatchEvent(new DragEvent('drop', {{bubbles:true, cancelable:true, dataTransfer:dt}}));
        t.dispatchEvent(new ClipboardEvent('paste', {{bubbles:true, cancelable:true, clipboardData:dt}}));
      }}
      const inp = document.querySelector('input[type="file"]');
      if (inp) {{ Object.defineProperty(inp,'files',{{value:dt.files,configurable:true}});
        inp.dispatchEvent(new Event('change',{{bubbles:true}})); }}
      return 'ok';
    }})()
    """
    wb.evaluate(js)
    print("[3/6] 等表单就绪（约 75s）", flush=True)
    ok = _wait(wb, "!!document.querySelector('input[placeholder*=\"填写作品标题\"]')", timeout=150, every=5)
    if not ok:
        raise WBError("表单 150s 内没就绪，可能视频没传上")
    wb.evaluate("""
      (() => { const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim()==='我知道了');
        if (b) b.click(); return 1; })()
    """)
    print("[4/6] 填标题 + 简介", flush=True)
    r = wb.evaluate(f"""
      (() => {{
        const inp = document.querySelector('input[placeholder*="填写作品标题"]');
        const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
        s.call(inp, {json.dumps(title)});
        inp.dispatchEvent(new Event('input',{{bubbles:true}}));
        const ed = document.querySelector('div[contenteditable="true"]');
        if (!ed) return 'no desc editor';
        ed.focus();
        document.execCommand('selectAll', false, null);
        document.execCommand('insertText', false, {json.dumps(desc)});
        return JSON.stringify({{t: inp.value.length, d: (ed.innerText||'').trim().length}});
      }})()
    """)
    print(f"  填入: {r}", flush=True)
    print("[5/6] AI 自主声明", flush=True)
    wb.evaluate("""
      (() => { const s = [...document.querySelectorAll('*')].find(e => e.children.length===0
        && (e.textContent||'').includes('请选择自主声明'));
        if (s) s.click(); return !!s; })()
    """)
    time.sleep(2)
    wb.evaluate("""
      (() => { const span = [...document.querySelectorAll('span')].find(e => e.textContent.trim()==='内容由AI生成');
        if (span) { (span.closest('.semi-radio')||span.parentElement).click(); span.click(); }
        return !!span; })()
    """)
    time.sleep(1)
    wb.evaluate("""
      (() => { const b = [...document.querySelectorAll('button, span.semi-button-content')]
          .find(e => e.textContent.trim()==='确定');
        if (b) (b.closest('button')||b).click(); return !!b; })()
    """)
    time.sleep(2)
    print("[6/6] 发布", flush=True)
    wb.evaluate("""
      (() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim()==='发布');
        if (b) b.click(); return !!b; })()
    """)
    time.sleep(4)
    _sms_verify(wb)
    ok = _wait(wb, "location.href.includes('content/manage?enter_from=publish')", timeout=60)
    if not ok:
        raise WBError("60s 内没跳到内容管理，检查页面状态")
    print("✅ 发布成功", flush=True)


def comment(video_id, text):
    wb = WB()
    wb.bring_to_front()
    wb.focus_emulation(True)
    wb.navigate(f"https://www.douyin.com/video/{video_id}")
    time.sleep(12)
    wb.evaluate("""
      (() => { const s = [...document.querySelectorAll('span')].find(e => e.textContent.trim()==='留下你的精彩评论吧');
        if (!s) return 'no comment entry';
        (s.closest('div[class]')||s.parentElement).click(); return 'clicked'; })()
    """)
    time.sleep(2)
    if not wb.evaluate("!!document.querySelector('.public-DraftEditor-content[contenteditable=\"true\"]')"):
        raise WBError("评论编辑器没打开")
    wb.evaluate("document.querySelector('.public-DraftEditor-content').focus(); 1")
    wb.cdp("Input.insertText", text=text)
    time.sleep(2)
    n = wb.evaluate("(() => { const ed = document.querySelector('.public-DraftEditor-content'); return ed ? ed.innerText.length : 0; })()")
    print(f"  编辑器字数 {n}", flush=True)
    wb.evaluate("""
      (() => { const box = document.getElementById('comment-input-container');
        const el = box && (box.querySelector('.wchsYBpK') || [...box.querySelectorAll('span')].filter(s => s.offsetWidth===36).pop());
        if (el) for (const t of ['mousedown','mouseup','click']) el.dispatchEvent(new MouseEvent(t,{bubbles:true}));
        return !!el; })()
    """)
    time.sleep(3)
    _sms_verify(wb)
    time.sleep(3)
    ok = wb.evaluate("document.body.innerText.includes('作者') && !document.body.innerText.includes('暂无评论')")
    if not ok:
        raise WBError("评论似乎没发出去")
    print("✅ 评论成功", flush=True)


def login():
    """登录态掉了：creator.douyin.com 短信登录（自动读码）。"""
    wb = WB()
    wb.bring_to_front()
    wb.focus_emulation(True)
    wb.navigate(UPLOAD)
    time.sleep(8)
    wb.evaluate("""
      (() => { const b = document.querySelector('.gKXDWaPG');
        if (b) b.click(); return !!b; })()
    """)
    time.sleep(12)
    code, _ = sms_latest(mark=True)
    if not code:
        raise WBError("收不到短信验证码")
    print(f"  [sms] 验证码 {code}", flush=True)
    wb.evaluate(f"""
      (() => {{
        const inputs = [...document.querySelectorAll('input')].filter(i => i.offsetParent);
        const codeInp = inputs.find(i => /验证码/.test(i.placeholder||'')) || inputs[inputs.length-1];
        const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
        s.call(codeInp, '{code}');
        codeInp.dispatchEvent(new Event('input',{{bubbles:true}}));
        const b = document.querySelector('.r7j70rK2');
        if (b) b.click();
        return 'code entered';
      }})()
    """)
    time.sleep(8)
    print("当前 URL:", wb.current_url())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("publish")
    p.add_argument("video")
    p.add_argument("--title", required=True)
    p.add_argument("--desc", default="")
    c = sub.add_parser("comment")
    c.add_argument("video_id")
    c.add_argument("--text", required=True)
    sub.add_parser("login")
    a = ap.parse_args()
    if a.cmd == "publish":
        publish(a.video, a.title, a.desc)
    elif a.cmd == "comment":
        comment(a.video_id, a.text)
    elif a.cmd == "login":
        login()

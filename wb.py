"""wb.py — Kimi WebBridge 极简客户端。

本机 Chrome 装了 Kimi 扩展后暴露 http://127.0.0.1:10086/command。
所有抖音/B站的网页自动化都通过它执行。

用法：
    from wb import WB
    wb = WB()
    wb.evaluate("location.href")
    wb.cdp("Input.insertText", text="你好")

要点（血泪换的）：
- WebBridge 标签页默认是后台标签：截图/IntersectionObserver/Draft.js 编辑器
  都不可靠 → 自动化前先 bring_to_front() + focus_emulation(True)
- 页面离开会弹 beforeunload（丢稿）→ 发布流程中途不要 navigate 走
- 遇到 "A JavaScript ... dialog is open" → dismiss_dialog()
"""
import base64
import json
import urllib.request

BASE = "http://127.0.0.1:10086/command"


class WBError(RuntimeError):
    pass


class WB:
    def __init__(self, base=BASE, timeout=120):
        self.base = base
        self.timeout = timeout

    def cmd(self, action, **args):
        payload = {"action": action, "args": args}
        req = urllib.request.Request(
            self.base, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                d = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise WBError(f"HTTP {e.code}: {e.read().decode()[:300]}")
        if not d.get("ok"):
            raise WBError(json.dumps(d.get("error"), ensure_ascii=False))
        return d.get("data")

    # ---- 常用封装 ----
    def evaluate(self, code, await_promise=False, timeout=None):
        """在页面上下文执行 JS。返回 value（returnByValue）。"""
        old = self.timeout
        if timeout:
            self.timeout = timeout
        try:
            d = self.cmd("evaluate", code=code, awaitPromise=await_promise,
                         returnByValue=True)
        finally:
            self.timeout = old
        if isinstance(d, dict) and "value" in d:
            return d["value"]
        return d

    def cdp(self, method, **params):
        return self.cmd("cdp", method=method, params=params)

    def navigate(self, url):
        return self.cmd("navigate", url=url)

    def current_url(self):
        return self.evaluate("location.href")

    def read_page(self):
        return self.cmd("read_page").get("text", "")

    def screenshot(self):
        """返回截图路径（需标签页在前台才可信）。"""
        return self.cmd("screenshot").get("path")

    def bring_to_front(self):
        return self.cdp("Page.bringToFront")

    def focus_emulation(self, enabled=True):
        """后台标签必须开，否则点击不送达。"""
        return self.cdp("Emulation.setFocusEmulationEnabled", enabled=enabled)

    def dismiss_dialog(self):
        return self.cmd("dialog", action="dismiss")

    def mouse_click(self, selector):
        return self.cmd("mouse_click", selector=selector)

    # ---- 高层工具 ----
    def file_to_b64_js(self, path, var_name="__b64"):
        """读本地文件 → JS 里的 base64 字符串变量。"""
        b64 = base64.b64encode(open(path, "rb").read()).decode()
        return f'const {var_name} = "{b64}";'

    def b64_to_uint8(self, var_name="__b64", out_name="__u8"):
        return (f'const {out_name} = (() => {{ const bin = atob({var_name});'
                f'const u = new Uint8Array(bin.length);'
                f'for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);'
                f'return u; }})();')

    def xhr(self, js_expr):
        """在页面里执行一段返回 Promise 的 JS 并等结果（内部模板见 douyin/bili 模块）。"""
        return self.evaluate("(async () => { %s })()" % js_expr,
                             await_promise=True, timeout=180)

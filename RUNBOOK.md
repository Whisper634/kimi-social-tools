# RUNBOOK — 成名之路自动化运维手册

> 本目录（`fame/tools/`）是发布流程的工具层。所有坑都固化在代码里，本文档解释"为什么"。
>  last verified: 2026-10-03（六集 EP1–EP6 双平台全链路实测通过）

## 工具总览

| 工具 | 用途 | 依赖 |
|---|---|---|
| `wb.py` | WebBridge 客户端（操控本机 Chrome） | Chrome 装 Kimi 扩展，端口 10086 |
| `sms.py` | 从 macOS「信息」读短信验证码 | 本机 chat.db 读取权限 |
| `douyin.py` | 抖音：publish / comment / login | wb.py + sms.py |
| `bili.py` | B站：refresh-cookies / publish / comment / ensure-pinned | wb.py（仅上传时）+ bili_cookies.json |
| `shots_lint.py` | 分镜 JSON 出片前静态检查 | content-pipeline/visual.py |

## 通用前提

1. **梯子**：抖音/B站不需要；X 需要。跑之前确认梯子状态，别让 Cookie 在错误网络环境下失效。
2. **Chrome 必须有一个标签页已激活过扩展**：Kimi 扩展每个会话第一次要在 chrome://extensions 点开一次（或重启 Chrome 后随便点一下扩展图标），否则 10086 端口无响应。
3. **后台标签问题**：WebBridge 操作的标签页如果在后台，点击不送达、截图不可信、Draft.js 编辑器不响应。`WB.bring_to_front()` + `WB.focus_emulation(True)` 是每次自动做的，**不要关掉**。
4. **对话框**：遇到 `"A JavaScript ... dialog is open"` → `wb.dismiss_dialog()`。
5. **payload 格式**：WebBridge 的 POST body 是 `{"action": ..., "args": {...}}`——字段名是 **action**，不是 tool/name/method。
6. **离开上传页 = 丢稿**：抖音/B站上传页都有 beforeunload。发布流程中**绝对不要** navigate 去别的页面查东西，所有检查用 XHR/CDP 在页面内完成。

## 抖音（douyin.py）

- **标题 30 字硬限制**：超长不是报错而是静默截断——工具内直接拒绝 >30 字的标题（`TITLE_LIMIT`）。写文案时先数字数。
- **视频注入**：input[type=file] 的 files 属性是只读的，要用 `Object.defineProperty` 覆盖 + change 事件；同时补 drop/paste 事件兜底。
- **简介**：contenteditable 必须用 `execCommand('insertText')`，直接改 innerText 不触发 React 状态。
- **短信验证面板**：发布/评论触发的 second-verify 面板里，「验证」按钮是 **div 不是 button**，且与「取消」贴在一起——坐标点击会误中「取消」浪费一个验证码，必须 JS `dispatchEvent` 精确点（工具已固化）。
- **评论输入框**：是 Draft.js 编辑器，`execCommand` 会崩，必须用 CDP `Input.insertText`。
- **评论发送按钮**：`#comment-input-container` 内 36×36 的 `span.wchsYBpK`（class 名会轮换，按尺寸兜底）。
- **成功标志**：跳到 `content/manage?enter_from=publish`。
- **验证码为什么频繁**（2026-10-01 实测 6 次）：新账号 + 新设备 + 高频自动化操作触发风控，**不是代码 bug**。养号期过后频率会降。sms.py 有 `.sms_used.json` 防复用。
- **登录态掉了**：`python3 douyin.py login`（短信登录全自动）。

## B站（bili.py）

- **Cookie**：`refresh-cookies` 从 Chrome CDP `Network.getAllCookies` 抓 `.bilibili.com` 域，存 `bili_cookies.json`（chmod 600）。SESSDATA 约一个月过期；接口返回 -101 就重抓。
- **直传不走官方上传组件**（UPOS 协议）：
  - init 用 **POST** `?uploads&output=json`，PUT 会被 411 拒（浏览器禁设 Content-Length）。
  - add/v3 注册的 `filename` **不带 .mp4 扩展名**（带了报 21015）。
  - 全程页面内 XHR，fetch 被站点包装会失败；分块上传 `withCredentials=false`。
- **评论置顶**：接口是 `/x/v2/reply/top`，**不是** `/top/add`（404）。参数 `action=1` 置顶。
- **审核期行为**：审核中的稿件评论**可提交但不可见**；置顶会失败，等过审后重试。`ensure-pinned(aid)` 是幂等的，定时任务用它轮询。
- **批量脚本教训**：先 `r[:200]` 截断响应再 `json.loads` 会把 rpid 截掉——解析失败必须报出来，不能静默继续（本次 EP2–6 置顶失败、靠定时任务兜底的根源）。

## 分镜 lint（shots_lint.py）

出片前必跑：`python3 shots_lint.py <shots.json>`。

- ERROR = 已发布就回不去的可见残次（出血裁切、出卡、撞字幕条、时间轴重叠）→ 退出码 1。
- WARN = 压批注分隔线，出片前人工看一眼。
- 2026-10-03 全量回扫结果：EP3 有 2 行出血、EP4 有 1 行出血（已发布，教训来源）；EP1/EP6 干净。

## 常见排错顺序

1. WebBridge 无响应 → Chrome 扩展是否激活过（见通用前提 2）
2. 点击不生效 → 标签页是否在后台（focus_emulation）
3. 接口 -101 → refresh-cookies
4. 抖音要验证码 → sms.py（6 分钟有效窗口，读不到就等下一条）
5. 页面弹了原生对话框 → dismiss_dialog

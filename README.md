# kimi-social-tools

抖音 / B站内容发布自动化的本地工具集（Kimi WebBridge + macOS）。
所有网页自动化通过本机 Chrome 的 Kimi 扩展暴露的 WebBridge 端口（127.0.0.1:10086）执行，坑全部固化在代码里。

## 工具一览

| 文件 | 用途 |
|---|---|
| `wb.py` | WebBridge 极简客户端（evaluate / CDP / 截图 / 对话框处理） |
| `sms.py` | 从 macOS「信息」chat.db 读取最新短信验证码（只读，防复用） |
| `douyin.py` | 抖音：publish / comment / login（全自动短信验证） |
| `bili.py` | B站：refresh-cookies / publish（UPOS 直传）/ comment / ensure-pinned |
| `shots_lint.py` | 视频分镜 JSON 出片前静态检查（出血 / 超行 / 时间轴重叠） |
| `RUNBOOK.md` | 运维手册：每个坑的「为什么」和排错顺序 |

## 依赖

- macOS + Chrome（安装 Kimi 扩展，每个会话先在 chrome://extensions 激活一次，否则 10086 端口无响应）
- Python 3 标准库，无第三方依赖
- `bili.py` 需要先用 `python3 bili.py refresh-cookies` 从 Chrome 抓取登录 Cookie 到本地
- `shots_lint.py` 依赖 `../content-pipeline/visual.py`（版式常量与文字测量函数，属另一个项目，未包含在本仓库）。独立使用时请自行提供同名模块

## 安全说明

- `bili_cookies.json`（B站登录 Cookie）与 `.sms_used.json`（验证码使用记录）已被 `.gitignore` 排除，绝不入库
- 本仓库只含工具代码，不含任何密钥、Cookie 或个人凭证

## 快速开始

```bash
python3 douyin.py publish video.mp4 --title "标题（≤30字）" --desc "简介"
python3 bili.py publish video.mp4 --title "标题" --desc "简介"
python3 shots_lint.py path/to/shots.json
```

排错与注意事项见 [RUNBOOK.md](RUNBOOK.md)。

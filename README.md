# Muse 连接助手

让 Muse（AI 助手）通过 HTTP 接口访问你的 Windows 本地电脑。

> **首次使用请先阅读 [使用说明.md](使用说明.md)**：包含环境安装、目录配置、本机验证、快速隧道、可直接复制给 Muse 的鉴权与接口说明，以及停止和排错步骤。

## 这是什么

一个轻量级的本地 HTTP 网关，运行在你的 Windows 电脑上。Muse 通过它可以：
- 读写指定目录下的文件
- 执行允许形式的命令或脚本（git、Python、PowerShell）
- 使用 Token 鉴权、文件路径限制和请求日志

**不是**向日葵/TeamViewer 那种人控人的远程桌面，而是**专门给 AI 开的本地接入通道**。Muse 端还需要具备相应的 HTTP 工具调用能力。

## 安全设计与边界

- **Token 鉴权**：除 `/api/health` 外的接口需要有效 Token，推荐使用 `X-Token` 请求头；首次运行自动生成
- **路径限制**：文件接口操作限定在 `BASE` 配置目录内
- **执行权限**：限制命令启动形式，但不是系统级沙箱；脚本仍拥有启动账户的权限
- **IP 限制**：直接访问只接受本机和 Tailscale 网段；Cloudflare 转发会被视为本机请求，受保护接口主要依靠 Token
- **审计日志**：请求日志写入程序同目录的 `agent.log`
- **停止方式**：前台服务、后台服务和隧道是独立进程；关闭启动提示窗口不代表它们都已停止

## 快速开始

### 要求

- Windows 10+
- Python 3.8+（推荐仍受支持的版本，本机已验证 3.13.12）；确保 `python` 和一键脚本所需的 `pythonw.exe` 可用
- 使用 Cloudflare 隧道时，还需要准备 `cloudflared.exe`，放在 `src` 或 PATH 中

### 安装

1. 下载本仓库，解压到自己的程序目录。
2. 复制 `src/config.example.json` 为 `src/config.local.json`，设置 `base_dir` 为自己的业务项目目录，并确认目录存在；已有本地配置不要覆盖。
3. 首次双击 `src/win_agent_start.bat`，先验证本机 `/api/health` 和带 Token 的 `/api/ls`。
4. 需要远程访问时，准备 cloudflared，再运行 `src/一键启动助手.bat`。
5. Token 位于 `src/token.txt`，仅填入可信 Muse 的私密工具配置，不要公开分享。
6. 保持需要的服务和隧道进程运行；完整步骤见 [使用说明.md](使用说明.md)。

`config.local.json`、Token、日志、cloudflared 程序和实际隧道配置已加入忽略规则。不要强制提交这些本地文件，也不要把真实路径或凭据写回公开模板。没有本地配置时，服务默认使用用户主目录下的 `MuseWorkspace`，该目录需事先准备好。

### 远程访问（可选）- 双模式

**快速隧道模式**（默认，无需账号或域名配置）：
准备好 Python 和 cloudflared 后，双击 `src/一键启动助手.bat`。没有 `src/cloudflared-winagent.yml` 时自动选择快速隧道，保留 `.example` 模板即可。
- 优点：无需注册 Cloudflare 账号、绑定域名或填写隧道配置
- 缺点：URL 每次创建隧道时随机（形如 `https://xxx.trycloudflare.com`），隧道重启后需更新 Muse 的服务地址；没有长期可用性保障

**固定域名模式**（进阶）：
1. 按 [Cloudflare 官方流程](https://developers.cloudflare.com/tunnel/get-started/)准备账号、隧道和域名路由。
2. 复制 `src/cloudflared-winagent.yml.example` 为 `src/cloudflared-winagent.yml`。
3. 填入自己的隧道 ID、凭据文件路径和域名。
4. 双击 `src/一键启动助手.bat`，检测到配置文件后尝试固定隧道模式。

### 启动与停止注意

快速隧道不需要上述固定配置。用完后，在 cloudflared 窗口按 `Ctrl+C` 断开公网访问；后台本地助手需要另外停止。

`tunnel.bat` 只适用于固定隧道；`停止助手.bat` 根据当前目录的完整脚本路径和固定隧道配置定位进程。旧版或手动相对路径启动的进程可能无法匹配，快速隧道也需要在对应窗口停止。请按 [使用说明.md](使用说明.md) 核对实际状态。

## 文件说明

| 文件 | 说明 |
|------|------|
| `src/win_agent.py` | 核心 HTTP 服务，从本地配置加载项目目录 |
| `src/config.example.json` | 公开配置模板；真实目录保存在被忽略的 config.local.json 中 |
| `src/tray_app.py` | 托盘程序，使用当前 Python 和内存生成的通用图标；额外依赖和固定隧道需单独准备 |
| `src/win_agent_start.bat` | 本地启动脚本（显示 Token，保留服务窗口） |
| `src/一键启动助手.bat` | 尝试启动后台助手和隧道，成功与否需检查接口 |
| `src/tunnel.bat` | 固定隧道脚本，使用同目录的 cloudflared 和配置文件 |
| `src/停止助手.bat` | 按本目录路径定位本地助手和固定隧道；快速隧道需另外停止 |
| `src/cloudflared-winagent.yml.example` | 隧道配置模板 |

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查（无需鉴权） |
| `/api/ls?path=` | GET | 列目录 |
| `/api/cat?path=` | GET | 读文件 |
| `/api/put?path=` | POST | 写文件 |
| `/api/exec` | POST | 执行允许形式的命令或脚本（进阶） |

所有接口（除 `/api/health`）需要在 Header 中带 `X-Token`，值为原始 Token，不加 Bearer 或 Token 前缀。当前不支持用 `Authorization` 头鉴权。

根路径 `/` 没有接口：无有效 Token 时返回 `401 bad token`，带正确 Token 时返回 `404 unknown api`。请使用表中的具体路径。

`/api/cat` 返回原始文件内容；`/api/put` 的 POST 正文也应是完整文件内容，不是 JSON 包装，且会覆盖同名文件。完整请求示例和可复制给 Muse 的说明见 [使用说明.md](使用说明.md)。

## 开机自启

项目不会自动注册开机自启。确认配置和访问权限后，可以手动将所需启动脚本的快捷方式放入 `shell:startup`。首次使用应先验证手动启动和停止流程，不要未经确认就让公网隧道随开机开启。托盘版需要先适配本机环境。

## 开发验证

在仓库根目录运行：

```powershell
python -B -m unittest discover -s tests -v
```

测试使用临时目录和模拟调用验证本地配置、路径边界、鉴权与读取行为，不启动真实 HTTP 服务或隧道，也不读写业务项目。

## 许可证

MIT License - 见 [LICENSE](LICENSE)

## 免责

本工具会授予持有有效 Token 的调用者文件操作和脚本执行能力，不应视为强隔离沙箱。请：
- 妥善保管 Token；轮换时先停止隧道和本地助手，再删除 `token.txt` 并重启，更新 Muse 的凭据
- 不要公开 Token 或随意暴露端口；不使用时停止隧道
- 修改业务文件前先备份或准备 Git 回退点
- 定期查看 `agent.log` 审计操作

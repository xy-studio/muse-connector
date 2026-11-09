# -*- coding: utf-8 -*-
"""
Muse 连接助手 - 系统托盘托管程序
- 常驻右下角托盘，右键菜单：状态 / Token(点击复制) / 网址(点击复制) / 启停服务
- 启动时自动确保小助手 + 隧道在运行（幂等）
- 单实例保护（占用 18790 端口作为锁）
- 出错写 tray_error.log
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

# ---- 单实例锁：已有实例在跑就直接退出 ----
try:
    import win32api
    import win32event
    _mutex = win32event.CreateMutex(None, False, "MuseAgentTrayMutex")
    if win32api.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)
except ImportError:
    _lock = socket.socket()
    try:
        _lock.bind(("127.0.0.1", 18790))
    except OSError:
        sys.exit(0)

AGENT_DIR = Path(__file__).resolve().parent
PYW = str(Path(sys.executable).with_name("pythonw.exe"))
if not Path(PYW).is_file():
    PYW = sys.executable
AGENT_PY = AGENT_DIR / "win_agent.py"
CF = AGENT_DIR / "cloudflared.exe"
CF_CFG = AGENT_DIR / "cloudflared-winagent.yml"
CF_LOG = AGENT_DIR / "cloudflared-live.log"
TOKEN_FILE = AGENT_DIR / "token.txt"
CONFIG_FILE = AGENT_DIR / "config.local.json"
CONFIG = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig")) if CONFIG_FILE.exists() else {}
if not isinstance(CONFIG, dict) or not isinstance(CONFIG.get("public_url", ""), str):
    raise ValueError("config.local.json 的 public_url 必须是字符串")
URL = CONFIG.get("public_url", "").strip()
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def read_token():
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "(token.txt 未找到)"


def agent_running():
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", 18789))
        s.close()
        return True
    except OSError:
        return False


def tunnel_running():
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "$config = Join-Path $env:MUSE_AGENT_DIR 'cloudflared-winagent.yml'; "
         "if (Get-CimInstance Win32_Process -Filter \"Name='cloudflared.exe'\" "
         "| Where-Object { $_.CommandLine -and "
         "($_.CommandLine.IndexOf($config, [StringComparison]::OrdinalIgnoreCase) -ge 0) }) "
         "{ exit 0 } else { exit 1 }"],
        env={**os.environ, "MUSE_AGENT_DIR": str(AGENT_DIR)},
        capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0


def start_services():
    if not agent_running():
        subprocess.Popen([PYW, str(AGENT_PY)], creationflags=NO_WINDOW)
        time.sleep(2)
    if CF_CFG.is_file() and not tunnel_running():
        log = open(CF_LOG, "wb")
        subprocess.Popen([str(CF), "tunnel", "--config", str(CF_CFG),
                          "--edge-ip-version", "4", "run"],
                         stderr=log, stdout=log, creationflags=NO_WINDOW)


def stop_services():
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "$agent = Join-Path $env:MUSE_AGENT_DIR 'win_agent.py'; "
         "$config = Join-Path $env:MUSE_AGENT_DIR 'cloudflared-winagent.yml'; "
         "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ("
         "($_.Name -match '^pythonw?[.]exe$' -and "
         "$_.CommandLine.IndexOf($agent, [StringComparison]::OrdinalIgnoreCase) -ge 0) -or "
         "($_.Name -eq 'cloudflared.exe' -and "
         "$_.CommandLine.IndexOf($config, [StringComparison]::OrdinalIgnoreCase) -ge 0)) } "
         "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
        env={**os.environ, "MUSE_AGENT_DIR": str(AGENT_DIR)},
        capture_output=True, creationflags=NO_WINDOW)


def copy_text(text):
    escaped = text.replace("'", "''")
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Set-Clipboard -Value '{escaped}'"],
                   capture_output=True, creationflags=NO_WINDOW)


def status_text(_item=None):
    a = "运行中" if agent_running() else "已停止"
    t = "运行中" if tunnel_running() else "已停止"
    return f"状态：小助手 {a} / 隧道 {t}"


def bg(fn):
    threading.Thread(target=fn, daemon=True).start()


def create_tray_image():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill=(76, 110, 140, 255))
    draw.ellipse((23, 23, 41, 41), fill=(240, 244, 248, 255))
    return image


def main():
    import pystray

    def on_restart(icon, item):
        def _do():
            stop_services()
            time.sleep(2)
            start_services()
        bg(_do)

    def on_stop(icon, item):
        bg(stop_services)

    def on_start(icon, item):
        bg(start_services)

    def on_copy_token(icon, item):
        copy_text(read_token())

    def on_copy_url(icon, item):
        copy_text(URL)

    def on_open_dir(icon, item):
        os.startfile(str(AGENT_DIR))

    def on_quit(icon, item):
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(status_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda i: f"Token: {read_token()}", on_copy_token),
        pystray.MenuItem(f"网址: {URL or '未配置'}（点击复制）", on_copy_url, enabled=bool(URL)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("启动服务", on_start),
        pystray.MenuItem("停止服务", on_stop),
        pystray.MenuItem("重启服务", on_restart),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("打开日志目录", on_open_dir),
        pystray.MenuItem("退出托盘（服务继续运行）", on_quit),
    )

    icon = pystray.Icon("MuseAgent", create_tray_image(), "Muse 连接助手（右键管理）", menu)
    # 托盘启动时自动确保服务在运行
    threading.Timer(1.0, start_services).start()
    icon.run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        (AGENT_DIR / "tray_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        sys.exit(1)

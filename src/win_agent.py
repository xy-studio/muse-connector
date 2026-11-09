# -*- coding: utf-8 -*-
"""
win_agent.py — Muse Windows 连接助手

作用：通过 HTTP API 访问本地配置指定的项目目录，
      支持本机、Tailscale 私网或本机 cloudflared 隧道转发。

安全设计：
  - 监听 0.0.0.0，但只应答 Tailscale 网段（100.64.0.0/10）与本机
  - 除健康检查外，接口要求有效 Token，推荐使用 Header X-Token
  - 文件操作限定在配置目录内，防目录穿越；脚本执行不属于系统级沙箱
  - 命令执行只允许三种固定形式（git / python 跑站内脚本 / powershell 跑站内 ps1）
  - token.txt 与 agent.log 保存在程序同目录，不应提交到版本库

用法：
  1. 复制 config.example.json 为 config.local.json，设置 base_dir
  2. 运行本文件，将 Token 填入可信 AI 工具的私密配置
  3. 保持服务进程运行，前台运行时按 Ctrl+C 停止

要求：Python 3.8+；远程访问需另行配置网络通道
"""

import ipaddress
import json
import secrets
import subprocess
import sys
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = AGENT_DIR / "config.local.json"


def load_base() -> Path:
    if not CONFIG_FILE.exists():
        return (Path.home() / "MuseWorkspace").resolve()
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("config.local.json 必须是 JSON 对象")
    value = config.get("base_dir")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("config.local.json 的 base_dir 必须是非空路径")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else AGENT_DIR / path).resolve()


BASE = load_base()
TOKEN_FILE = AGENT_DIR / "token.txt"
LOG_FILE = AGENT_DIR / "agent.log"
PORT = 18789

# 只允许 Tailscale 网段 + 本机
ALLOWED_NETS = [ipaddress.ip_network("100.64.0.0/10"),
                ipaddress.ip_network("127.0.0.0/8")]


def get_token() -> str:
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    tok = secrets.token_hex(16)
    TOKEN_FILE.write_text(tok, encoding="utf-8")
    return tok


TOKEN = get_token()


def log(msg: str):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def client_allowed(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in n for n in ALLOWED_NETS)
    except ValueError:
        return False


def safe_path(rel: str) -> Path:
    """把相对路径限定在 BASE 内，防穿越（兼容 \\ 写法）"""
    rel = rel.replace("\\", "/").lstrip("/")
    p = (BASE / rel).resolve()
    if p != BASE.resolve() and BASE.resolve() not in p.parents:
        raise ValueError("路径越界")
    return p


class Handler(BaseHTTPRequestHandler):
    server_version = "MuseWinAgent/2.0"

    def _auth(self) -> bool:
        hdr = self.headers.get("X-Token", "")
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        q = qs.get("token", [""])[0]
        import hmac
        return hmac.compare_digest(hdr, TOKEN) or hmac.compare_digest(q, TOKEN)

    def _send(self, code: int, obj, ctype="application/json"):
        if isinstance(obj, (dict, list)):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        elif isinstance(obj, str):
            body = obj.encode("utf-8")
        else:
            body = obj
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _route(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        return u.path, qs

    def _guard(self) -> bool:
        if not client_allowed(self.client_address[0]):
            log(f"拒绝非 Tailscale 来源: {self.client_address[0]}")
            self._send(403, {"ok": False, "error": "forbidden network"})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        path, qs = self._route()
        log(f"GET {path} from {self.client_address[0]}")
        if path == "/api/health":
            return self._send(200, {"ok": True, "base": str(BASE)})
        if not self._auth():
            return self._send(401, {"ok": False, "error": "bad token"})
        try:
            if path == "/api/ls":
                p = safe_path(qs.get("path", [""])[0])
                items = []
                for c in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
                    st = c.stat()
                    items.append({"name": c.name, "is_dir": c.is_dir(),
                                  "size": st.st_size,
                                  "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
                return self._send(200, {"ok": True, "items": items})
            if path == "/api/cat":
                p = safe_path(qs.get("path", [""])[0])
                if not p.is_file():
                    return self._send(404, {"ok": False, "error": "not a file"})
                return self._send(200, p.read_bytes(), "application/octet-stream")
        except ValueError as e:
            return self._send(403, {"ok": False, "error": str(e)})
        except Exception as e:
            return self._send(500, {"ok": False, "error": str(e)})
        return self._send(404, {"ok": False, "error": "unknown api"})

    def do_POST(self):
        if not self._guard():
            return
        path, qs = self._route()
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        log(f"POST {path} ({len(body)}B) from {self.client_address[0]}")
        if not self._auth():
            return self._send(401, {"ok": False, "error": "bad token"})
        try:
            if path == "/api/put":
                p = safe_path(qs.get("path", [""])[0])
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(body)
                return self._send(200, {"ok": True, "size": len(body)})
            if path == "/api/exec":
                req = json.loads(body.decode("utf-8") or "{}")
                return self._send(200, run_tool(req))
        except ValueError as e:
            return self._send(403, {"ok": False, "error": str(e)})
        except Exception as e:
            return self._send(500, {"ok": False, "error": str(e)})
        return self._send(404, {"ok": False, "error": "unknown api"})

    def log_message(self, *a):
        pass  # 用自己的 log


def run_tool(req: dict) -> dict:
    """只允许三种固定形式，不拼 shell"""
    tool = req.get("tool")
    args = req.get("args", [])
    cwd = safe_path(req.get("cwd", ""))
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        return {"ok": False, "error": "bad args"}

    if tool == "git":
        cmd = ["git"] + args
    elif tool == "python":
        script = safe_path(args[0]) if args else None
        if not script or not script.is_file() or script.suffix != ".py":
            return {"ok": False, "error": "python 只允许跑站内 .py 脚本"}
        cmd = [sys.executable, str(script)] + args[1:]
    elif tool == "ps1":
        script = safe_path(args[0]) if args else None
        if not script or not script.is_file() or script.suffix not in (".ps1", ".cmd", ".bat"):
            return {"ok": False, "error": "只允许跑站内 ps1/cmd/bat"}
        cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)] + args[1:]
    else:
        return {"ok": False, "error": f"未知 tool: {tool}"}

    log(f"EXEC {' '.join(cmd[:4])}… cwd={cwd}")
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, timeout=180)
        return {"ok": True, "returncode": r.returncode,
                "stdout": r.stdout.decode("utf-8", "replace")[-8000:],
                "stderr": r.stderr.decode("utf-8", "replace")[-8000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout(180s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    print("=" * 60)
    print("Muse Windows 连接助手正在运行")
    print(f"监听: 0.0.0.0:{PORT}（仅应答 Tailscale 网段 + 本机）")
    print(f"Token: {TOKEN}")
    print("请将 Token 填入可信 AI 工具的私密配置")
    print("日志:", LOG_FILE)
    print("关闭本窗口即停止服务")
    print("=" * 60, flush=True)
    log("agent 启动")
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

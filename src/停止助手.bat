@echo off
setlocal
set "MUSE_AGENT_DIR=%~dp0"
echo 正在停止本目录的连接助手和固定隧道...
powershell -NoProfile -Command "$agent = Join-Path $env:MUSE_AGENT_DIR 'win_agent.py'; $config = Join-Path $env:MUSE_AGENT_DIR 'cloudflared-winagent.yml'; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and (($_.Name -match '^pythonw?[.]exe$' -and $_.CommandLine.IndexOf($agent, [StringComparison]::OrdinalIgnoreCase) -ge 0) -or ($_.Name -eq 'cloudflared.exe' -and $_.CommandLine.IndexOf($config, [StringComparison]::OrdinalIgnoreCase) -ge 0)) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo 停止指令已执行，请检查服务状态。
echo 快速隧道请在对应窗口按 Ctrl+C 停止。
timeout /t 3 >nul

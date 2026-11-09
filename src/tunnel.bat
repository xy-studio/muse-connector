@echo off
cd /d "%~dp0"
echo cloudflared 隧道运行中（读取固定隧道配置）
echo 日志: %~dp0cloudflared-live.log
echo 关闭本窗口 = 断开隧道
echo.
"%~dp0cloudflared.exe" tunnel --config "%~dp0cloudflared-winagent.yml" --edge-ip-version 4 run > "%~dp0cloudflared-live.log" 2>&1
echo.
echo [异常] 隧道已退出，详情看 cloudflared-live.log
pause

@echo off
if "%~1"=="--utf8" goto :main
chcp 65001 >nul
:: Reopen in a fresh cmd so UTF-8 is used from the start of batch parsing.
"%ComSpec%" /d /c ""%~f0" --utf8"
exit /b %errorlevel%

:main
cd /d "%~dp0"

echo ============================================
echo  Muse 连接助手 - 智能启动
echo ============================================
echo.

:: 1. 启动 win_agent（如果没在跑）
tasklist /FI "IMAGENAME eq pythonw.exe" 2>nul | find /I "pythonw.exe" >nul
if errorlevel 1 (
    echo [1/2] 启动本地服务...
    start "" pythonw.exe "%~dp0win_agent.py"
    timeout /t 3 /nobreak >nul
) else (
    echo [1/2] 本地服务已在运行，跳过
)

:: 2. 启动隧道（智能选择模式）
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>nul | find /I "cloudflared.exe" >nul
if not errorlevel 1 (
    echo [2/2] 隧道已在运行，跳过
    goto :done
)

if exist "cloudflared-winagent.yml" (
    echo [2/2] 检测到固定隧道配置，使用固定域名模式...
    start "Muse隧道-固定" cloudflared.exe tunnel --config "%~dp0cloudflared-winagent.yml" run
) else (
    echo [2/2] 未检测到隧道配置，使用快速隧道模式（URL 每次随机）...
    echo       如需固定域名，请复制 cloudflared-winagent.yml.example
    echo       为 cloudflared-winagent.yml 并填入你的隧道信息
    echo.
    start "Muse隧道-快速" cloudflared.exe tunnel --url http://localhost:18789
)

:done
echo.
echo ============================================
echo  启动完成！
echo  - 本地服务: http://localhost:18789
echo  - 查看隧道 URL 请看 "Muse隧道" 窗口
echo  - Token 在 token.txt，首次运行已自动生成
echo ============================================
timeout /t 6 /nobreak >nul

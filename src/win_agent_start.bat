@echo off
if "%~1"=="--utf8" goto :main
chcp 65001 >nul
:: Reopen in a fresh cmd so UTF-8 is used from the start of batch parsing.
"%ComSpec%" /d /c ""%~f0" --utf8"
exit /b %errorlevel%

:main
cd /d "%~dp0"

:: Find Python (prefer python, then the py launcher).
set "PYEXE="
where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
  where py >nul 2>&1 && set "PYEXE=py -3"
)
if not defined PYEXE (
  echo [错误] 没找到 Python。请安装 Python 3.8+（安装时勾选 Add python.exe to PATH）。
  pause & exit /b 1
)
if not exist win_agent.py (
  echo [错误] win_agent.py 不在当前目录。
  echo        请把 win_agent.py 和本文件放在同一个目录后再双击。
  pause & exit /b 1
)

:: Start the agent; token.txt is written next to this script.
start "Muse Agent - Keep Open" %PYEXE% "%~dp0win_agent.py"
echo 正在启动小助手，请稍候...

:: Wait up to 20 seconds for token.txt.
set "TOKEN="
for /L %%i in (1,1,20) do (
  if exist token.txt (
    for /f "usebackq delims=" %%t in ("token.txt") do set "TOKEN=%%t"
    if defined TOKEN goto :ok
  )
  timeout /t 1 /nobreak >nul
)
:ok
if not defined TOKEN (
  echo [错误] 20 秒仍没读到 token.txt，请看「Muse Agent - Keep Open」窗口里的报错。
  pause & exit /b 1
)

:: Copy the token without a trailing newline.
powershell -NoProfile -Command "Set-Clipboard -Value ((Get-Content token.txt -Raw).Trim())"

echo.
echo ============================================================
echo  小助手已启动，Token 已自动复制到剪贴板：
echo  %TOKEN%
echo.
echo  请将 Token 填入可信 AI 工具的私密配置。
echo  保持「Muse Agent - Keep Open」窗口开着，不要关闭。
echo ============================================================
pause

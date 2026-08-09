@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"
set PORT=8655

set "PY=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" (
  set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
)
if not exist "%PY%" (
  echo ============================================
  echo  未找到 Python，无法启动本地服务
  echo  请改用 http:// 方式打开本页面
  echo ============================================
  pause
  exit /b 1
)

echo ============================================
echo  岐黄智脑 · 养生板块 本地服务
echo  正在启动，浏览器将自动打开…
echo  访问地址: http://127.0.0.1:%PORT%/yangsheng.html
echo  关闭本窗口即停止服务
echo ============================================

start "" "http://127.0.0.1:%PORT%/yangsheng.html"
"%PY%" -m http.server %PORT% --bind 127.0.0.1
if errorlevel 1 (
  echo.
  echo 服务启动失败，请按任意键退出…
  pause >nul
)

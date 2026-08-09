@echo off
chcp 65001 >nul 2>&1
setlocal
rem 切换到本 bat 所在目录
cd /d "%~dp0"
set PORT=8657
set HTML=capabilities.html
set TITLE=岐黄智脑·能力上架管理

set "PY=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" (
  set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
)
if not exist "%PY%" (
  echo ============================================
  echo  未找到 Python，无法启动本地服务
  echo  请安装 Python 3.12 或更高版本后重试
  echo ============================================
  pause
  exit /b 1
)

echo ============================================
echo  %TITLE% 本地服务
echo  访问地址: http://127.0.0.1:%PORT%/%HTML%
echo  关闭本窗口即停止服务
echo ============================================
echo.

rem 检测端口是否已被占用（直接连，不依赖 netstat 文本）
powershell -Command "try { $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', %PORT%); $c.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
  echo  [警告] 端口 %PORT% 已被占用，说明上次服务还在运行。
  echo  如果浏览器已打开，请直接访问：
  echo    http://127.0.0.1:%PORT%/%HTML%
  echo  否则请先关闭之前打开的同类黑色窗口，再重新双击本文件。
  echo.
  pause
  exit /b 1
)

rem 在子窗口中启动 http.server（失败时子窗口保留错误信息）
start "%TITLE% 服务" /MIN cmd /c "%PY% -m http.server %PORT% --bind 127.0.0.1"

rem 循环探测端口，最多等 10 秒
echo  正在等待服务启动...
set /a n=0
:LOOP
timeout /t 1 /nobreak >nul
powershell -Command "try { $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', %PORT%); $c.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 goto READY
set /a n+=1
if %n% lss 10 goto LOOP

echo.
echo  [错误] 服务启动失败，无法连接 127.0.0.1:%PORT%
echo  可能原因：
echo    1. Python 运行异常（查看另一个黑色窗口的错误）
echo    2. 安全软件/防火墙拦截了本地端口
echo    3. 端口 %PORT% 被其他程序占用
echo  解决后请关闭所有相关黑色窗口，再重新双击本文件。
echo.
pause
exit /b 1

:READY
echo  [就绪] 服务已启动，正在打开浏览器...
echo.
start "" "http://127.0.0.1:%PORT%/%HTML%"
echo  浏览器已打开。请保持本窗口运行。
echo  关闭本窗口即可停止服务。
pause >nul

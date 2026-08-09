@echo off
chcp 65001 >nul 2>&1
setlocal
rem 切换到本 bat 所在目录
cd /d "%~dp0"
set PORT=8659
set HTML=console.html
set TITLE=岐黄智脑·运营控制台

set "NODE=C:\Users\Administrator\.workbuddy/binaries\node\versions\22.22.2\node.exe"
if not exist "%NODE%" (
  set "NODE=C:\Program Files\nodejs\node.exe"
)
if not exist "%NODE%" (
  set "NODE=node.exe"
)
where %NODE% >nul 2>&1
if errorlevel 1 (
  echo ============================================
  echo  未找到 Node.js，无法启动本地代理服务
  echo  请安装 Node.js 18+ 后重试
  echo ============================================
  pause
  exit /b 1
)

echo ============================================
echo  %TITLE% 本地一体化服务
echo  （静态页面 + API 反向代理，全程走 127.0.0.1，绕开 8602 公网拦截）
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

rem 在子窗口中启动本地代理服务（失败时子窗口保留错误信息）
start "%TITLE% 服务" /MIN cmd /c "%NODE% local-server.mjs"

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
echo    1. Node.js 运行异常（查看另一个黑色窗口的错误）
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

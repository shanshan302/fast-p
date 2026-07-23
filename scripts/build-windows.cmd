@echo off
setlocal
set "BUILD_SCRIPT=%~dp0build-windows.ps1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%BUILD_SCRIPT%" %*
exit /b %ERRORLEVEL%

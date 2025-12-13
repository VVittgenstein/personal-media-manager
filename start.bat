@echo off
setlocal EnableExtensions

set "LAUNCHER=%~dp0infra\windows\start.bat"
if not exist "%LAUNCHER%" (
  echo [ERROR] Missing launcher: %LAUNCHER%
  echo Please ensure the repository is complete.
  pause
  exit /b 1
)

call "%LAUNCHER%" %*
exit /b %ERRORLEVEL%

@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..\\..") do set "REPO_ROOT=%%~fI"
set "CONFIG_PATH=%REPO_ROOT%\config\backend.json"
set "PS_SCRIPT=%~dp0start.ps1"
set "MEDIA_ROOT_OVERRIDE=%~1"

if not exist "%PS_SCRIPT%" (
  echo [ERROR] Missing PowerShell script: %PS_SCRIPT%
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -RepoRoot "%REPO_ROOT%" -ConfigPath "%CONFIG_PATH%" -MediaRoot "%MEDIA_ROOT_OVERRIDE%"

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] Launch failed. exit code=%EXIT_CODE%
  pause
)
exit /b %EXIT_CODE%

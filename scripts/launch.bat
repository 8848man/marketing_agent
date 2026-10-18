@echo off
rem Shared launcher for start.bat / start-review.bat (Windows).
rem Creates .venv in this folder, installs requirements.txt, starts the local dashboard.
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
set MODE=%~1
echo == Unmyeongwon YouTube comment dashboard %MODE% ==
set PY=
where py >nul 2>nul && py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>nul && set PY=py -3
if not defined PY (
  where python >nul 2>nul && python -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>nul && set PY=python
)
if not defined PY (
  echo Python 3.11+ is required. Install it from https://www.python.org/downloads/ and run this file again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo 1/3 Creating .venv ...
  %PY% -m venv .venv || goto :fail
)
if not exist ".venv\.requirements-installed" (
  echo 2/3 Installing packages, first run only - 1 to 3 minutes ...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail
  echo done> ".venv\.requirements-installed"
)
echo 3/3 Starting the dashboard. A browser opens shortly. Close this window or press Ctrl+C to stop.
".venv\Scripts\python.exe" -m marketing_agent dashboard --port 8770 --port-tries 10 %MODE%
goto :eof
:fail
echo Setup failed. See the message above.
pause
exit /b 1

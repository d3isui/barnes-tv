@echo off
rem Barnes Television Broadcasting System - Windows launcher. First run creates a private Python environment.
title Barnes Television Broadcasting System
cd /d "%~dp0"
set PY=python
where py >nul 2>nul
if %errorlevel%==0 set PY=py -3
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment...
  %PY% -m venv .venv || goto :nopython
)
".venv\Scripts\python.exe" -c "import sys; print('Using Python ' + sys.version.split()[0])"
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :essentials
goto :run
:essentials
echo.
echo Some optional packages could not be installed. Installing the essentials only.
echo Casting to Chromecast may be unavailable - see README, Troubleshooting.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q "Pillow>=10.1" || goto :pipfail
:run
".venv\Scripts\python.exe" broadcast.py %*
goto :eof
:nopython
echo.
echo Python 3.10 or newer is required. Install it with:  winget install Python.Python.3.12
echo or from https://www.python.org/downloads/ - tick "Add python.exe to PATH"
pause
goto :eof
:pipfail
echo Could not install requirements. Check your internet connection and try again.
pause

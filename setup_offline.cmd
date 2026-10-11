@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (python -m venv .venv) else (py -3 -m venv .venv)
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install --force-reinstall --no-index --find-links wheelhouse powerapps-sim==0.1.0
if errorlevel 1 exit /b 1
echo Installed. Run start.cmd

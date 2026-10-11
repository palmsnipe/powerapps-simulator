@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m powerapps_sim %*

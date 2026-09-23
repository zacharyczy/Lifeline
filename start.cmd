@echo off
setlocal
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%~dp0lifeline.py"
) else (
  start "" python "%~dp0lifeline.py"
)

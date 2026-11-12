@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal
call "%~dp0_python_find.cmd"
if not defined PYTHON_EXE (
 echo [ERROR] Python 3.9 or newer is required.
 echo Install Python from https://www.python.org/downloads/windows/
 pause
 exit /b 1
)
"%PYTHON_EXE%" "%~dp0whale50.py"
if errorlevel 1 (
 echo [ERROR] Whale50 exited abnormally.
 pause
)
endlocal

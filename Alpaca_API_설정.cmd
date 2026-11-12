@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_python_find.cmd"
if not defined PYTHON_EXE (
 echo Python 3.9+ required
 pause
 exit /b 1
)
"%PYTHON_EXE%" "%~dp0alpaca_setup.py"
pause

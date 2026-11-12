@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_python_find.cmd"
if not defined PYTHON_EXE (
 echo Python was not found.
 pause
 exit /b 1
)
"%PYTHON_EXE%" "%~dp0install_daily.py" --remove
pause

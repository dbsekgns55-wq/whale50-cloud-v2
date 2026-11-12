@echo off
set "PYTHON_EXE="
for %%P in (
 "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
 "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
 "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
 "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
 "C:\Program Files (x86)\Python\Python313\python.exe"
 "C:\Program Files\Python313\python.exe"
 "C:\Python313\python.exe"
 "C:\Python312\python.exe"
) do (
 if not defined PYTHON_EXE if exist "%%~P" set "PYTHON_EXE=%%~P"
)
if not defined PYTHON_EXE (
 for /f "delims=" %%P in ('where python 2^>nul') do (
  if not defined PYTHON_EXE echo "%%P"|find /i "WindowsApps" >nul || if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
 )
)
if not defined PYTHON_EXE (
 for /f "delims=" %%P in ('where py 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
)

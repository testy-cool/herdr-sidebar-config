@echo off
rem Herdr resolves hook commands itself and only appends .exe, so a PATH
rem "python" may be a shim for an unexpected interpreter. Prefer the one
rem setup recorded, then the py launcher, then python.
setlocal
cd /d "%~dp0" || exit /b 1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HS_PYTHON="
if not defined HERDR_PLUGIN_CONFIG_DIR goto launcher
if not exist "%HERDR_PLUGIN_CONFIG_DIR%\python-path.txt" goto launcher
rem The record is UTF-8 without a BOM. Each hook or popup owns its console,
rem so the code page change ends with this process.
chcp 65001 >nul 2>&1
set /p HS_PYTHON=<"%HERDR_PLUGIN_CONFIG_DIR%\python-path.txt"
if not defined HS_PYTHON goto launcher
if not exist "%HS_PYTHON%" goto launcher
"%HS_PYTHON%" sidebar.py %*
exit /b %errorlevel%

:launcher
where py >nul 2>&1 || goto python
py -3 sidebar.py %*
exit /b %errorlevel%

:python
python sidebar.py %*
exit /b %errorlevel%

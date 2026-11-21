@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title QwenBlender

echo [1/3] Checking for updates on main (git pull) ...
where git >nul 2>nul
if errorlevel 1 goto :no_git
if not exist ".git" goto :no_git
git pull --ff-only origin main
if errorlevel 1 echo       Update skipped: pull failed or there are local changes. Using the current version.
goto :env

:no_git
echo       git not found or not a git folder. Update skipped.

:env
echo [2/3] Preparing Python environment ...
where uv >nul 2>nul
if not errorlevel 1 goto :use_uv
where python >nul 2>nul
if not errorlevel 1 goto :use_python
where py >nul 2>nul
if not errorlevel 1 goto :use_py
echo.
echo   Neither uv nor Python was found.
echo   Install uv with:   winget install astral-sh.uv
echo   then run this file again.
goto :end

:use_uv
if not exist ".venv\Scripts\python.exe" uv venv .venv --python 3.12
if errorlevel 1 goto :fail
uv pip install --python ".venv\Scripts\python.exe" -q -r requirements.txt
if errorlevel 1 goto :fail
goto :run

:use_python
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto :fail
goto :pip

:use_py
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto :fail

:pip
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail

:run
echo [3/3] Starting ...
echo.
".venv\Scripts\python.exe" -m qb %*
goto :end

:fail
echo.
echo   Setting up the Python environment failed. See the messages above.

:end
echo.
pause

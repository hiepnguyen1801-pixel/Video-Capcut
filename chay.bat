@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
    python capcut_edit.py %*
) else (
    py capcut_edit.py %*
)
echo.
pause

@echo off
cd /d "%~dp0"

echo Running run_tracking.py from %cd%
echo.

python run_tracking.py

echo.
echo ============================================
echo Finished (Exit Code: %ERRORLEVEL%)
echo ============================================

timeout /t 3 /nobreak >nul
exit
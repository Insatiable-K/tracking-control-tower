@echo off
cd /d "%~dp0"
echo Running run_tracking.py from %cd%
echo.
python run_tracking.py
echo.
echo ============================================
echo Finished (exit code %ERRORLEVEL%). Press any key to close.
echo ============================================
pause >nul

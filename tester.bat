@echo off
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
where python >nul 2>nul && (python tester.py) || (py -3 tester.py)
pause

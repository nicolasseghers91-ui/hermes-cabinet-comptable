@echo off
rem Met a jour BOFiP (le lundi), codes Legifrance (incremental) et BOSS.
rem Sans argument : tout, avec pause a la fin. Avec "auto" (tache planifiee) : pas de pause, BOFiP le lundi seulement.
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "LOG=%~dp0journal_mises_a_jour.log"

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  echo Python est introuvable. Installe-le avec : scoop install python
  echo [%date% %time%] Python introuvable >> "%LOG%"
  if /i not "%~1"=="auto" pause
  exit /b 1
)

set "AUTO=0"
if /i "%~1"=="auto" set "AUTO=1"
set "DOW=1"
for /f %%d in ('powershell -NoProfile -Command "[int](Get-Date).DayOfWeek"') do set "DOW=%%d"
set "BOFIP=1"
if "%AUTO%"=="1" if not "%DOW%"=="1" set "BOFIP=0"

echo ==== %date% %time% : debut des mises a jour >> "%LOG%"
echo Mises a jour en cours (journal : %LOG%)...
if "%BOFIP%"=="1" (
  call :etape "BOFiP" construire
) else (
  echo [%time%] BOFiP : ignore aujourd'hui, mise a jour le lundi >> "%LOG%"
)
call :etape "Codes Legifrance" construire-lois
call :etape "BOSS" mise-a-jour-boss
echo ==== %date% %time% : fin >> "%LOG%"

echo.
echo Termine. Consulte le journal : %LOG%
if "%AUTO%"=="0" pause
exit /b 0

:etape
echo [%time%] %~1 : debut >> "%LOG%"
echo   %~1...
%PY% doctrine_mcp.py %~2 >> "%LOG%" 2>&1
echo [%time%] %~1 : code retour %errorlevel% >> "%LOG%"
exit /b 0

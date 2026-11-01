@echo off
cd /d "%~dp0"
echo Telechargement et indexation du BOSS (boss.gouv.fr), environ 2 minutes...
where python >nul 2>nul
if %errorlevel%==0 (
  python doctrine_mcp.py mise-a-jour-boss
) else (
  where py >nul 2>nul
  if %errorlevel%==0 (
    py -3 doctrine_mcp.py mise-a-jour-boss
  ) else (
    echo Python est introuvable. Installe-le avec : scoop install python
  )
)
echo.
echo Termine. Previens Claude.
pause

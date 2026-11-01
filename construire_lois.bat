@echo off
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  python doctrine_mcp.py construire-lois
) else (
  where py >nul 2>nul
  if %errorlevel%==0 (
    py -3 doctrine_mcp.py construire-lois
  ) else (
    echo Python est introuvable. Installe-le avec : scoop install python
  )
)
pause

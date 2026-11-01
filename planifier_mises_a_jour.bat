@echo off
cd /d "%~dp0"
echo Creation de la tache planifiee des mises a jour (tous les jours a 12h30)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0planifier_mises_a_jour.ps1"
echo.
echo Pour la supprimer : powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0planifier_mises_a_jour.ps1" -Supprimer
pause

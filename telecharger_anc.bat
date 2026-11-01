@echo off
cd /d "%~dp0"
if not exist "donnees\anc" mkdir "donnees\anc"
echo Telechargement des normes comptables de l'ANC (environ 15 Mo)...
set "UA=Mozilla/5.0"
set "B=https://www.anc.gouv.fr/files/anc/files/1_Normes_fran%%C3%%A7aises"
powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -UserAgent '%UA%' -Uri '%B%/recueil/2026/PCG--1er-janvier-2026.pdf' -OutFile 'donnees\anc\pcg-2026.pdf'"
powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -UserAgent '%UA%' -Uri '%B%/recueil/2026/Recueil-PCG-Janvier-2026-2-.pdf' -OutFile 'donnees\anc\recueil-entreprises-2026.pdf'"
powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -UserAgent '%UA%' -Uri '%B%/Reglements/Recueils/Recueil_Secteur-non-lucratif/2026/Recueil-non-lucratif-2026.pdf' -OutFile 'donnees\anc\recueil-non-lucratif-2026.pdf'"
powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -UserAgent '%UA%' -Uri '%B%/recueil/REGLT-2020_01-VERSION-RECUEIL2026.pdf' -OutFile 'donnees\anc\reglement-2020-01-comptes-consolides.pdf'"
echo.
dir /b "donnees\anc"
echo.
echo Termine. Previens Claude.
pause

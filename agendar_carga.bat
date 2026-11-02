@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Agenda a carga para todo dia as 13:05 (as fontes atualizam entre 00h e 12h)
schtasks /Create /SC DAILY /ST 13:05 /TN "PainelCustodia\CargaDiaria" /TR "\"%~dp0carga_diaria.bat\"" /F
if %errorlevel%==0 (echo Carga agendada para 13:05 todos os dias.) else (echo Nao consegui agendar. Rode este arquivo como administrador.)
pause

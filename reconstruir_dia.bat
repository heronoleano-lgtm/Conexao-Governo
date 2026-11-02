@echo off
chcp 65001 >nul
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\PainelCustodia\venv
call "%VENV%\Scripts\activate.bat"
if "%1"=="" (set /p DIA=Dia a reconstruir [AAAA-MM-DD]: ) else (set DIA=%1)
python -m custodia.repositorio %DIA%
pause

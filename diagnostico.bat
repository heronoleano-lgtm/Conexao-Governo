@echo off
chcp 65001 >nul
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\PainelCustodia\venv
call "%VENV%\Scripts\activate.bat"
python -m custodia.diagnostico
pause

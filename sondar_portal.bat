@echo off
chcp 65001 >nul
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\PainelCustodia\venv
call "%VENV%\Scripts\activate.bat"
echo Testando a API do Portal da Transparencia (uma chamada por conjunto, campos reais)...
python -m custodia.portal_api
pause

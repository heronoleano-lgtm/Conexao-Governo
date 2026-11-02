@echo off
chcp 65001 >nul
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\PainelCustodia\venv
call "%VENV%\Scripts\activate.bat"
echo Auditando a ultima carga bruta contra o painel...
python -m custodia.auditoria
pause

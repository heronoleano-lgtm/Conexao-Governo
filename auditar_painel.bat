@echo off
chcp 65001 >nul
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\PainelCustodia\venv
call "%VENV%\Scripts\activate.bat"
echo Auditando os numeros que o painel mostra (percentuais, totais, duplicidades, territorio)...
python -m custodia.auditoria_painel
pause

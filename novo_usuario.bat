@echo off
chcp 65001 >nul
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\PainelCustodia\venv
call "%VENV%\Scripts\activate.bat"
set /p LOGIN=Login: 
set /p NOME=Nome completo: 
set /p PERFIL=Perfil (gestao, comercial ou administrador): 
python -m custodia.acesso adicionar %LOGIN% "%NOME%" %PERFIL%
pause

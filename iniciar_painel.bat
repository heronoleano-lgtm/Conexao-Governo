@echo off
chcp 65001 >nul
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\PainelCustodia\venv
call "%VENV%\Scripts\activate.bat"
echo Abrindo o painel em http://localhost:8501 ...
streamlit run telas\app.py

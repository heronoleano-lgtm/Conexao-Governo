@echo off
chcp 65001 >nul
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\PainelCustodia\venv
echo === Painel de Custodia - instalacao ===
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul || (echo Python nao encontrado. Instale o Python 3.12 em python.org marcando "Add to PATH". & pause & exit /b 1)
if not exist "%VENV%" (
  echo Criando ambiente virtual...
  %PY% -m venv "%VENV%" || (echo Falha ao criar o ambiente. & pause & exit /b 1)
)
call "%VENV%\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
echo Instalando bibliotecas (alguns minutos)...
pip install -r requirements.txt || (echo Falha na instalacao das bibliotecas. & pause & exit /b 1)
echo.
echo === Testes automaticos ===
python -m pytest -q
echo.
echo === Teste de conexao com as fontes ===
python -m custodia.diagnostico
echo.
if not exist config\usuarios.yaml (
  echo === Crie o primeiro usuario (administrador) ===
  set /p LOGIN=Login: 
  set /p NOME=Nome completo: 
  call python -m custodia.acesso adicionar %%LOGIN%% "%%NOME%%" administrador
)
echo.
echo Instalacao concluida. Proximo passo: carga_diaria.bat
pause

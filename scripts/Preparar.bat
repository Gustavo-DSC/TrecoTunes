@echo off
setlocal
title TrecoTunes - Preparacao
cd /d "%~dp0.."

echo ========================================
echo       TRECO TUNES - PREPARACAO
echo ========================================
echo.

if not exist "requirements.txt" (
    echo ERRO: requirements.txt nao encontrado!
    pause
    exit /b 1
)

echo [1/3] Procurando Python...
where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=py -3"
    goto :python_found
)
where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python"
    goto :python_found
)
echo ERRO: Python nao encontrado!
pause
exit /b 1

:python_found
echo Python encontrado!
echo.
echo [2/3] Criando ambiente virtual...
if not exist ".venv\Scripts\python.exe" (
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo ERRO ao criar ambiente virtual!
        pause
        exit /b 1
    )
) else (
    echo Ambiente virtual ja existe.
)

echo.
echo [3/3] Instalando dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERRO ao instalar dependencias!
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip uninstall -y numpy >nul 2>&1

echo.
echo ========================================
echo PREPARACAO CONCLUIDA!
echo ========================================
echo Agora rode scripts\Inicial.bat (cria o atalho) ou scripts\Player.bat
echo.
pause

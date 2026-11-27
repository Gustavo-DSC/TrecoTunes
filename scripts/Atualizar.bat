@echo off
title TrecoTunes - Atualizar
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo ERRO: Ambiente virtual nao encontrado. Rode scripts\Preparar.bat primeiro.
    pause
    exit /b 1
)

echo Atualizando pytubefix (corrige quando o YouTube muda algo)...
".venv\Scripts\python.exe" -m pip install --upgrade pytubefix
echo.
pause

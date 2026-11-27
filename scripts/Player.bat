@echo off
title TrecoTunes
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo ERRO: Ambiente virtual nao encontrado. Rode scripts\Preparar.bat primeiro.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" main.py

if errorlevel 1 (
    echo.
    echo O TrecoTunes foi encerrado com erro. Veja data\logs\player.log
    pause
)

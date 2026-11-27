@echo off
setlocal
title TrecoTunes - Atalho
cd /d "%~dp0.."

echo ========================================
echo          TRECO TUNES
echo ========================================
echo.
echo Criando atalho...
echo.

if not exist "scripts\Player.bat" (
    echo ERRO: scripts\Player.bat nao encontrado!
    pause
    exit /b 1
)
if not exist "assets\icon.ico" (
    echo ERRO: assets\icon.ico nao encontrado!
    pause
    exit /b 1
)

set "PLAYER=%~dp0Player.bat"
set "ICON=%CD%\assets\icon.ico"
set "WORKDIR=%CD%"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$desktop = [Environment]::GetFolderPath('Desktop'); $ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut((Join-Path $desktop 'TrecoTunes.lnk')); $s.TargetPath = $env:ComSpec; $s.Arguments = '/c \"\"' + $env:PLAYER + '\"\"'; $s.WorkingDirectory = $env:WORKDIR; $s.IconLocation = $env:ICON + ',0'; $s.Description = 'Iniciar TrecoTunes'; $s.Save()"

if errorlevel 1 (
    echo.
    echo ERRO: Nao foi possivel criar o atalho.
    pause
    exit /b 1
)

echo.
echo Atalho criado na Area de Trabalho!
echo.
pause

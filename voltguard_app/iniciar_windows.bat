@echo off
chcp 65001 >nul
title VoltGuard
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual .venv ...
    python -m venv .venv || (echo Python nao encontrado. Instale o Python 3.10+ e marque "Add to PATH". & pause & exit /b 1)
    echo Instalando dependencias ...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" iniciar.py %*
pause

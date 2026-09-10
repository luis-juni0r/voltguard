@echo off
chcp 65001 >nul
title VoltGuard - link publico (Cloudflare Tunnel)
cd /d "%~dp0"
echo ============================================================
echo  VoltGuard - gerando link publico para o app que esta rodando
echo  na porta 5000 deste PC (deixe o iniciar.py / app.py aberto).
echo ============================================================
if not exist cloudflared.exe (
    echo Baixando cloudflared.exe (uma vez so)...
    powershell -Command "Invoke-WebRequest -Uri https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe -OutFile cloudflared.exe"
    if not exist cloudflared.exe ( echo Falha no download. Baixe manualmente em https://github.com/cloudflare/cloudflared/releases & pause & exit /b 1 )
)
echo.
echo Procure abaixo uma linha com  https://XXXX.trycloudflare.com  -- esse e o link.
echo Ele vale enquanto esta janela ficar aberta. Ctrl+C encerra.
echo.
cloudflared.exe tunnel --url http://localhost:5000
pause

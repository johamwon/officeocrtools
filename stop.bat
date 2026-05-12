@echo off
chcp 65001 >nul
echo 正在停止所有服务...

:: 停止Python后端
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *run_backend*" >nul 2>&1
taskkill /F /IM uvicorn.exe >nul 2>&1

:: 停止LLM服务
taskkill /F /IM llama-server.exe >nul 2>&1

echo 所有服务已停止。
timeout /t 2 /nobreak >nul

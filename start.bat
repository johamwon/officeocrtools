@echo off
chcp 65001 >nul
title 文档解析系统

echo ============================================
echo   文档解析与合同管理系统 v0.2.0
echo ============================================
echo.

:: 确定目录
set BASE_DIR=%~dp0
set PYTHON=%BASE_DIR%runtime\python\python.exe
set LLAMA=%BASE_DIR%runtime\llama-server.exe
set MODEL=%BASE_DIR%models\llm\qwen2.5-coder-1.5b-instruct-q8_0.gguf

:: 检查是否使用嵌入式Python
if not exist "%PYTHON%" (
    echo [INFO] 未找到嵌入式Python，使用系统Python...
    set PYTHON=python
)

:: 启动LLM服务
if exist "%LLAMA%" (
    echo [1/3] 启动 LLM 服务...
    start /B "" "%LLAMA%" -m "%MODEL%" -c 4096 --port 8080 --log-disable > "%BASE_DIR%logs\llm.log" 2>&1
    timeout /t 3 /nobreak >nul
) else (
    echo [1/3] 跳过 LLM 服务（请确保已手动启动 llama-server 在端口 8080）
)

:: 启动后端
echo [2/3] 启动后端服务...
start /B "" "%PYTHON%" "%BASE_DIR%run_backend.py" > "%BASE_DIR%logs\backend.log" 2>&1

:: 等待服务就绪
echo [3/3] 等待服务就绪...
timeout /t 5 /nobreak >nul

:: 打开浏览器
echo.
echo 正在打开浏览器...
start http://localhost:8000

echo.
echo ============================================
echo   系统已启动！
echo   访问地址: http://localhost:8000
echo   关闭此窗口不会停止服务
echo   使用 stop.bat 停止所有服务
echo ============================================
echo.
pause

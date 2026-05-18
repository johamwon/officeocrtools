@echo off
chcp 65001 >nul
title 文档解析系统

echo ============================================
echo   文档解析与合同管理系统 v0.2.0
echo ============================================
echo.

:: 确定目录
set "BASE_DIR=%~dp0"
set "BASE_DIR=%BASE_DIR:~0,-1%"
set "PYTHON=%BASE_DIR%\runtime\python\python.exe"
set "APP_DIR=%BASE_DIR%\app"
set "MODELS_DIR=%BASE_DIR%\models\llm"

:: 环境变量
set "PADDLEX_HOME=%BASE_DIR%\models\paddleocr"
set "FLAGS_enable_pir_in_executor=0"
set "FLAGS_use_mkldnn=0"

:: 创建日志目录
if not exist "%BASE_DIR%\logs" mkdir "%BASE_DIR%\logs"

:: 检查Python
if not exist "%PYTHON%" (
    echo [INFO] 未找到嵌入式Python，使用系统Python...
    set "PYTHON=python"
)

:: 启动LLM服务（从配置文件读取启动命令）
echo [1/3] 启动 LLM 服务...
:: 使用Python解析配置文件获取启动命令
for /f "delims=" %%i in ('"%PYTHON%" -c "import configparser,sys; c=configparser.ConfigParser(); c.read(r'%BASE_DIR%\config\app.ini', encoding='utf-8'); cmd=c.get('llm','launch_command',fallback=''); print(cmd)" 2^>nul') do set "LLM_CMD=%%i"

if "%LLM_CMD%"=="" (
    echo   跳过（配置中未设置 launch_command，请手动启动LLM服务）
) else (
    :: 替换路径变量
    set "LLM_CMD=%LLM_CMD:{base_dir}=%BASE_DIR%%"
    set "LLM_CMD=%LLM_CMD:{models_dir}=%MODELS_DIR%%"

    :: 检查llama-server是否在runtime目录
    if exist "%BASE_DIR%\runtime\llama-server.exe" (
        set "LLM_CMD=%LLM_CMD:llama-server=%BASE_DIR%\runtime\llama-server.exe%"
    )

    echo   命令: %LLM_CMD%
    start "" /B %LLM_CMD% >"%BASE_DIR%\logs\llm.log" 2>&1
    timeout /t 5 /nobreak >nul
)

:: 启动后端
echo [2/3] 启动后端服务...
cd /d "%APP_DIR%"
start "" /B "%PYTHON%" run_backend.py >"%BASE_DIR%\logs\backend_stdout.log" 2>&1

:: 等待服务就绪
echo [3/3] 等待服务就绪（首次启动需要约30秒加载模型）...
timeout /t 30 /nobreak >nul

:: 检查端口
netstat -an | findstr ":8000" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo.
    start http://localhost:8000
    echo ============================================
    echo   系统已启动！
    echo   访问地址: http://localhost:8000
    echo   使用 stop.bat 停止所有服务
    echo ============================================
) else (
    echo.
    echo [WARNING] 后端可能未完全启动
    echo   查看日志: %BASE_DIR%\logs\backend_stdout.log
    echo ============================================
)
echo.
pause

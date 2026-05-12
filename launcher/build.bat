@echo off
echo 编译 DocParser 启动器...
echo.

:: 需要安装 Go: https://go.dev/dl/
:: go mod tidy
go build -ldflags="-H windowsgui -s -w" -o ..\dist\DocParser\DocParser.exe .

if %ERRORLEVEL% EQU 0 (
    echo ✓ 编译成功: ..\dist\DocParser\DocParser.exe
) else (
    echo ✗ 编译失败
)
pause

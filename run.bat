@echo off
chcp 65001 >nul

:: 检查uv是否可用
uv --version >nul 2>&1
if %errorlevel% equ 0 (
    echo 使用uv启动AVIF转换工具...
    uv run avif_converter.py
) else (
    :: 检查Python
    python --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo 错误: 未找到Python或uv，请先运行install.bat安装依赖
        pause
        exit /b 1
    )
    
    echo 使用Python启动AVIF转换工具...
    python avif_converter.py
)

pause 
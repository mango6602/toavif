@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo  ==============================
echo    AVIF转换工具 - 安装脚本
echo  ==============================
echo.

:: 检查uv是否安装
uv --version >nul 2>&1
if !errorlevel! equ 0 (
    echo [信息] 检测到uv版本:
    uv --version
    set USE_UV=1
) else (
    echo [信息] 未找到uv，使用pip安装
    set USE_UV=0
    
    :: 检查Python是否安装
    python --version >nul 2>&1
    if !errorlevel! neq 0 (
        echo [错误] 未找到Python，请先安装Python 3.7或更高版本
        echo.
        echo 下载地址: https://www.python.org/downloads/
        echo.
        pause
        exit /b 1
    )
    
    echo [信息] 检测到Python版本:
    python --version
)

echo.
if !USE_UV! equ 1 (
    echo [步骤1] 使用uv安装依赖包...
    uv add tkinterdnd2==0.3.0
    uv add pywin32>=227
    uv add winshell>=0.6
) else (
    echo [步骤1] 升级pip...
    python -m pip install --upgrade pip
    
    echo.
    echo [步骤2] 安装Python依赖包...
    pip install tkinterdnd2==0.3.0
    pip install pywin32>=227
    pip install winshell>=0.6
)

echo.
echo [步骤2] 检查FFmpeg...
ffmpeg -version >nul 2>&1
if !errorlevel! equ 0 (
    echo [成功] FFmpeg已安装
    ffmpeg -version | findstr "version"
) else (
    echo [警告] 未找到FFmpeg
    echo.
    echo 请手动安装FFmpeg:
    echo 1. 访问 https://ffmpeg.org/download.html#build-windows
    echo 2. 下载Windows版本并解压
    echo 3. 将ffmpeg.exe所在目录添加到系统PATH
    echo.
    echo 或者使用包管理器安装:
    echo   choco install ffmpeg
    echo   scoop install ffmpeg
)

echo.
echo  ==============================
echo [完成] 依赖安装完成！

echo.
echo 使用方法:
if !USE_UV! equ 1 (
    echo   uv run avif_converter.py
) else (
    echo   python avif_converter.py
)
echo.
echo 如果遇到问题，请查看README.md文档
echo  ==============================
echo.
pause 
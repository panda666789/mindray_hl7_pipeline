@echo off
chcp 65001 >nul 2>&1
title Mindray HL7 Pipeline - HL7采集端安装程序

echo ============================================
echo   Mindray HL7 数据采集系统 - HL7采集端安装程序
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    echo 下载地址: https://www.python.org/downloads/
    echo 安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

:: 显示 Python 版本
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] Python %PY_VER%

:: 获取项目根目录（install.bat 在 deploy/ 下）
set "PROJECT_DIR=%~dp0.."
pushd "%PROJECT_DIR%"
set "PROJECT_DIR=%CD%"
popd

echo [信息] 项目目录: %PROJECT_DIR%

:: 本地采集不需要第三方依赖
echo.
echo [信息] 本地 HL7 采集不需要安装第三方 Python 依赖
echo [提示] 如果以后要测试上传，请联网后手动运行:
echo        pip install -r "%PROJECT_DIR%\apps\client\requirements.txt"

:: 创建必要目录
echo.
echo [安装] 创建目录...
if not exist "%PROJECT_DIR%\logs" mkdir "%PROJECT_DIR%\logs"
if not exist "%PROJECT_DIR%\data" mkdir "%PROJECT_DIR%\data"
echo [OK] logs/ 和 data/ 目录已就绪

:: 运行安装验证
echo.
echo [验证] 正在检查安装...
python "%PROJECT_DIR%\deploy\verify_install.py"
if errorlevel 1 (
    echo.
    echo [警告] 部分检查未通过，请查看上方日志
) else (
    echo [OK] 安装验证通过
)

:: 创建桌面快捷方式
echo.
set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT=%DESKTOP%\MindrayHL7Collector.bat"
if not exist "%SHORTCUT%" (
    echo @echo off > "%SHORTCUT%"
    echo title Mindray HL7 Collector >> "%SHORTCUT%"
    echo cd /d "%PROJECT_DIR%" >> "%SHORTCUT%"
    echo call deploy\run_collector.bat >> "%SHORTCUT%"
    echo pause >> "%SHORTCUT%"
    echo [OK] 桌面快捷方式已创建: MindrayHL7Collector.bat
) else (
    echo [跳过] 桌面快捷方式已存在
)

echo.
echo ============================================
echo   [OK] Install complete!
echo   Double-click MindrayHL7Collector.bat on Desktop
echo ============================================
pause

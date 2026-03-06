@echo off
chcp 65001 >nul 2>&1
title Collector - HL7 数据采集

set "PROJECT_DIR=%~dp0.."
pushd "%PROJECT_DIR%"
set "PROJECT_DIR=%CD%"
popd

cd /d "%PROJECT_DIR%"

echo ============================================
echo   Mindray HL7 Collector (自动重启模式)
echo   按 Ctrl+C 停止
echo ============================================
echo.

:loop
echo [%date% %time%] 启动 Collector...
python apps\client\collector.py --config configs\client_config.json
echo.
echo [%date% %time%] Collector 已退出，5秒后自动重启...
timeout /t 5 /nobreak >nul
goto loop

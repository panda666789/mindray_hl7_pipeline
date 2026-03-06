@echo off
chcp 65001 >nul 2>&1
title PhysRecorder - 数据采集

set "PROJECT_DIR=%~dp0.."
pushd "%PROJECT_DIR%"
set "PROJECT_DIR=%CD%"
popd

cd /d "%PROJECT_DIR%"
python apps\client\PhysRecorder.py
if errorlevel 1 (
    echo.
    echo [错误] PhysRecorder 异常退出，请检查日志: logs\physrecorder.log
    pause
)

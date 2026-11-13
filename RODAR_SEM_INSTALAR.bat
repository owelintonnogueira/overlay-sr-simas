@echo off
chcp 65001 >nul
title Cortes de Live (modo teste)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_env.ps1"
if errorlevel 1 ( echo DEU ERRO na preparação. & pause & exit /b 1 )
"%~dp0.venv\Scripts\python.exe" "%~dp0app\main.py"
if errorlevel 1 pause

@echo off
chcp 65001 >nul
title Construindo o instalador - Cortes de Live
echo.
echo  Isso vai baixar as ferramentas e gerar o instalador (CortesLive-Setup.exe).
echo  Precisa de internet e leva de 10 a 25 minutos na primeira vez.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1"
if errorlevel 1 (
  echo.
  echo  DEU ERRO. Leia a mensagem acima. Se precisar, me mande um print.
) else (
  echo.
  echo  Abrindo a pasta do instalador...
  start "" "%~dp0installer_output"
)
pause

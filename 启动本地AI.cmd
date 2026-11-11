@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_local_ai.ps1"
if errorlevel 1 pause

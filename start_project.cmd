@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0start_project.ps1"

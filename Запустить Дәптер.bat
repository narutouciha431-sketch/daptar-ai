@echo off
chcp 65001 >nul
title Daptar AI - server
cd /d "%~dp0"
".venv\Scripts\python.exe" tools\run.py
pause

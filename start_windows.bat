@echo off
cd /d "%~dp0"
pythonw run_app.py
if errorlevel 1 (echo Install Python 3.12 with tkinter, or use the portable ZIP. & pause)

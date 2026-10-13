@echo off
REM Inicia la Libreria Salesiana. Luego abrir http://127.0.0.1:8000
cd /d "%~dp0"
set PYTHONUTF8=1
set PY=C:\Users\ESTUDIANTE\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=C:\Users\LABH\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python
"%PY%" -m pip install --quiet -r requirements.txt
start "" "http://127.0.0.1:8000"
"%PY%" run.py
pause

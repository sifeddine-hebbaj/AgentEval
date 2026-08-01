@echo off
REM Windows batch script to run the evaluation with environment variables loaded
cd /d "%~dp0"
for /f "tokens=*" %%a in (.env) do set %%a
python run_for_eval.py

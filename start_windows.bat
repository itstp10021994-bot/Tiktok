@echo off
REM Chay lich dang TikTok. Dat shortcut file nay vao shell:startup de tu chay khi bat may.
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe -m tiktok_scheduler run
) else (
    python -m tiktok_scheduler run
)
pause

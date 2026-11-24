@echo off
cd /d "%~dp0frontend"
start "EnergyGrid Frontend" cmd /k "npm run dev"
timeout /t 5 >nul
start http://localhost:3000

@REM  .\start-energygrid.bat   (type ts in terminal to start the backend server)
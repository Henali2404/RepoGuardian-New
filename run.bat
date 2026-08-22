@echo off
echo ===================================================
echo   Starting Autonomous Code Architect Fullstack...
echo ===================================================

echo [1/2] Launching Python FastAPI Backend on port 8000...
start "RepoGuardian Backend" cmd /k "cd backend && venv\Scripts\uvicorn main:app --reload --port 8000"

echo [2/2] Launching Next.js Frontend on port 3000...
start "RepoGuardian Frontend" cmd /k "cd frontend && npm run dev"

echo ===================================================
echo   Both servers started! 
echo   - Backend: http://localhost:8000
echo   - Frontend: http://localhost:3000
echo   - Close the opened command prompt windows to stop them.
echo ===================================================
pause

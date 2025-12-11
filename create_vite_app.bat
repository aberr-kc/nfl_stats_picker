@echo off
echo Creating Vite React NFL Stats App...
npm create vite@latest nfl-stats-vite -- --template react
cd nfl-stats-vite
npm install
npm install axios
echo.
echo Vite React app created! Next steps:
echo 1. Replace src/App.jsx with the provided React code
echo 2. Replace src/App.css with the provided CSS
echo 3. Run: npm run dev
echo 4. Your FastAPI backend will run on port 8000
echo 5. Vite frontend will run on port 5173
pause
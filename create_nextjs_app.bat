@echo off
echo Creating Next.js NFL Stats App...
npx create-next-app@latest nfl-stats-nextjs --typescript --tailwind --eslint --app --src-dir --import-alias "@/*"
cd nfl-stats-nextjs
npm install axios
echo.
echo Next.js app created! Next steps:
echo 1. Replace src/app/page.tsx with the provided Next.js code
echo 2. Run: npm run dev
echo 3. Your FastAPI backend will run on port 8000
echo 4. Next.js frontend will run on port 3000
pause
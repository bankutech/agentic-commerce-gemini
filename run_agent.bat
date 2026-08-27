@echo off
echo Starting Agentic Commerce FastAPI Server...
start "FastAPI Server" cmd /c "python main.py"

echo Waiting for server to start...
timeout /t 5 /nobreak >nul

echo Starting LangGraph Gemini Agent...
python -m agent.langgraph_agent
pause

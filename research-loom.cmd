@echo off
setlocal
uv run --frozen python "%~dp0research-loom" %*
set "_research_loom_exit=%ERRORLEVEL%"
endlocal & exit /b %_research_loom_exit%

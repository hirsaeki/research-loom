@echo off
setlocal
set "_research_loom_python=%~dp0.venv\Scripts\python.exe"
if not exist "%_research_loom_python%" (
  echo Research Loom runtime environment is not provisioned. Run `uv sync --frozen` outside the host sandbox first. 1>&2
  endlocal & exit /b 2
)
"%_research_loom_python%" "%~dp0research-loom" %*
set "_research_loom_exit=%ERRORLEVEL%"
endlocal & exit /b %_research_loom_exit%

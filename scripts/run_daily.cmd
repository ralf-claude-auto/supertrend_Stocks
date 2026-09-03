@echo off
rem Daily 07:00 routine for supertrend_Stocks, run by the "StockSupertrendPaperLog"
rem scheduled task. Inspect or drive it with:
rem   schtasks /query  /tn StockSupertrendPaperLog /v /fo list
rem   schtasks /run    /tn StockSupertrendPaperLog       (run it now)
rem   schtasks /delete /tn StockSupertrendPaperLog /f    (remove it)
rem
rem The task stores an ABSOLUTE path to this file, so if the project is moved
rem again the 07:00 run breaks silently - repoint it with Set-ScheduledTask.
rem This script itself is path-independent.
rem
rem WHY 07:00. Every session the scan needs has closed and been published by then:
rem XETRA settled 17:30 the previous day, New York 22:00 the previous day. So both
rem markets contribute a COMPLETE previous-day candle and are treated alike. Any
rem bar dated today is dropped - while a market is open Yahoo serves a PARTIAL bar,
rem and a gate computed on one can reverse by the close. An evening run would
rem silently skip the session it was meant to process. Mon-Fri: Monday's run covers
rem Friday, Tuesday's covers Monday, and so on.
rem
rem WHAT RUNS. Everything real lives in backtest\run_daily.py, which reads
rem paper\systems.json and drives each book in turn - scan, paper log, PDF, send.
rem Two books today (index and fox), so two reports arrive each morning. Adding or
rem removing one is an edit to systems.json; this file does not change.
rem
rem This wrapper exists only to locate the venv and capture output, because the
rem Task Scheduler gives a failing script nowhere to complain to.

cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo [%date% %time%] FATAL: .venv missing - run: py -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt >> paper\cron.log
    exit /b 1
)

echo. >> paper\cron.log
.venv\Scripts\python.exe backtest\run_daily.py >> paper\cron.log 2>&1
set RC=%errorlevel%
if not "%RC%"=="0" echo [ERROR] run_daily.py exited %RC% >> paper\cron.log
exit /b %RC%

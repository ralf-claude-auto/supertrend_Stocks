@echo off
rem Daily routine for Stock_Supertrend, run by the "StockSupertrendPaperLog"
rem scheduled task. Register or inspect it with:
rem   schtasks /query /tn StockSupertrendPaperLog /v /fo list
rem   schtasks /run   /tn StockSupertrendPaperLog      (run it now)
rem   schtasks /delete /tn StockSupertrendPaperLog /f  (remove it)
rem
rem TIMING MATTERS. Both scripts deliberately ignore any bar dated today, because
rem while a market is open Yahoo serves a PARTIAL bar and a SuperTrend flip
rem computed on one can vanish by the close. So this must run the MORNING AFTER
rem the session it is meant to process, not the same evening - an evening run
rem would silently skip that day. 07:00 local, Mon-Fri: Monday's run covers
rem Friday, Tuesday's covers Monday, and so on.

cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo [%date% %time%] FATAL: .venv missing - run: py -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt >> paper\cron.log
    exit /b 1
)

echo. >> paper\cron.log
echo ===== %date% %time% ===== >> paper\cron.log

rem The scan produces the human-readable list; the paper log tracks the simulated
rem book. The scan runs first so both see the same freshly refreshed data.
.venv\Scripts\python.exe backtest\scan_daily.py --watchlist watchlists\fox.txt >> paper\cron.log 2>&1
if errorlevel 1 echo [WARN] scan_daily exited %errorlevel% >> paper\cron.log

.venv\Scripts\python.exe backtest\paper_log.py >> paper\cron.log 2>&1
if errorlevel 1 echo [WARN] paper_log exited %errorlevel% >> paper\cron.log

echo ===== done %date% %time% ===== >> paper\cron.log
exit /b 0

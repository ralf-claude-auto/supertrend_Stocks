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
rem silently skip the session it was meant to process.
rem
rem Mon-Fri. Monday's run covers Friday, Tuesday's covers Monday, and so on.

cd /d "%~dp0.."

rem WHICH UNIVERSE TO SCAN. The Nasdaq-100 plus the DAX 40, 136 symbols, each
rem verified against data by backtest/build_watchlist.py. The alternatives are
rem watchlists\fox.txt (the original hand-built list) and watchlists\ranked.txt
rem (a filtered cut of it). This line is the only thing that decides.
rem
rem Walk-forward at 6 slots, total R captured: this list 528R against fox.txt's
rem 499R, and 698R once paper_log orders same-day candidates by paper\priority.csv
rem rather than taking whichever fired first.
rem
rem The UNION of both lists was WORSE than either alone - 405R. That is not a
rem paradox: with far more symbols than slots, first-come-first-served fills the
rem book with the EARLIEST signal, which says nothing about quality, and then
rem blocks better ones for days. Widening the universe only pays once the
rem ordering is fixed, which is what priority.csv does.
rem
rem Re-run rank_symbols.py periodically to refresh paper\priority.csv. A ranking
rem frozen for a year ranks symbols that USED to work.
set WATCHLIST=watchlists\nq100_dax40.txt

if not exist ".venv\Scripts\python.exe" (
    echo [%date% %time%] FATAL: .venv missing - run: py -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt >> paper\cron.log
    exit /b 1
)

echo. >> paper\cron.log
echo ===== %date% %time% ===== >> paper\cron.log

set FAILED=

rem 1. The scan. Refreshes data, applies the gate, writes scans\<session>.csv|md.
.venv\Scripts\python.exe backtest\scan_daily.py --watchlist "%WATCHLIST%" >> paper\cron.log 2>&1
if errorlevel 1 (
    echo [ERROR] scan_daily failed - nothing downstream can be trusted >> paper\cron.log
    set FAILED=1
    goto :done
)

rem 2. The simulated book, so the report can show open positions.
.venv\Scripts\python.exe backtest\paper_log.py >> paper\cron.log 2>&1
if errorlevel 1 echo [WARN] paper_log failed - report will omit open positions >> paper\cron.log

rem 3. The PDF, rendered from what the scan just wrote.
.venv\Scripts\python.exe backtest\report_pdf.py >> paper\cron.log 2>&1
if errorlevel 1 (
    echo [ERROR] report_pdf failed - nothing to send >> paper\cron.log
    set FAILED=1
    goto :done
)

rem 4. Delivery. Skipped quietly when no credentials are configured yet, but a
rem    CONFIGURED channel that fails is an error: a report that silently fails to
rem    send is worse than one that never existed, because you sit waiting for it.
if not exist "paper\delivery.json" (
    echo [INFO] paper\delivery.json absent - PDF written, not sent >> paper\cron.log
    goto :done
)
.venv\Scripts\python.exe backtest\deliver.py >> paper\cron.log 2>&1
if errorlevel 1 (
    echo [ERROR] delivery failed - the PDF is in reports\ but was not sent >> paper\cron.log
    set FAILED=1
)

:done
echo ===== done %date% %time% ===== >> paper\cron.log
if defined FAILED exit /b 1
exit /b 0

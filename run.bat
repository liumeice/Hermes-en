@echo off
REM Hermes-en Doc Scraper & PDF Generator
REM Usage: run.bat [step1|step2|step3|all]

call .venv\Scripts\activate.bat

if "%1"=="step1" (
    echo === Step 1: Scrape Sidebar ===
    .venv\Scripts\python.exe step1_scrape_sidebar.py
) else if "%1"=="step2" (
    echo === Step 2: Generate PDFs ===
    .venv\Scripts\python.exe step2_generate_pdfs.py
) else if "%1"=="step2-mt" (
    echo === Step 2: Generate PDFs (multi-threaded) ===
    .venv\Scripts\python.exe step2_generate_pdfs_mt.py %2
) else if "%1"=="step3" (
    echo === Step 3: Merge PDFs ===
    .venv\Scripts\python.exe step3_merge_pdfs.py
) else if "%1"=="all" (
    echo ============================================
    echo  Hermes-en Full Pipeline
    echo ============================================
    echo.
    echo Step 1: Scrape Sidebar
    .venv\Scripts\python.exe step1_scrape_sidebar.py
    if errorlevel 1 goto :error
    echo.
    echo Step 2: Generate PDFs
    .venv\Scripts\python.exe step2_generate_pdfs.py
    if errorlevel 1 goto :error
    echo.
    echo Step 3: Merge PDFs
    .venv\Scripts\python.exe step3_merge_pdfs.py
    if errorlevel 1 goto :error
    echo.
    echo ============================================
    echo  Complete!
    echo ============================================
) else (
    echo Usage: run.bat [step1^|step2^|step2-mt [workers]^|step3^|all]
    exit /b 1
)

goto :end

:error
echo.
echo *** Pipeline failed! ***
exit /b 1

:end
echo Done.

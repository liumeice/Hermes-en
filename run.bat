@echo off
REM Hermes-cn Doc Scraper ^& PDF Generator
REM Usage: run.bat [step1|step2|step3|all]

call venv\Scripts\activate.bat

if "%1"=="step1" (
    echo === Step 1: Scrape Sidebar ===
    python step1_scrape_sidebar.py
) else if "%1"=="step2" (
    echo === Step 2: Generate PDFs ===
    python step2_generate_pdfs.py
) else if "%1"=="step3" (
    echo === Step 3: Merge PDFs ===
    python step3_merge_pdfs.py
) else (
    echo ============================================
    echo  Hermes-cn Full Pipeline
    echo ============================================
    echo.
    echo Step 1: Scrape Sidebar
    python step1_scrape_sidebar.py
    if errorlevel 1 goto :error
    echo.
    echo Step 2: Generate PDFs
    python step2_generate_pdfs.py
    if errorlevel 1 goto :error
    echo.
    echo Step 3: Merge PDFs
    python step3_merge_pdfs.py
    if errorlevel 1 goto :error
    echo.
    echo ============================================
    echo  Complete!
    echo ============================================
)

goto :end

:error
echo.
echo *** Pipeline failed! ***
exit /b 1

:end
echo Done.

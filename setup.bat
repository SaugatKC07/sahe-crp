@echo off
echo SAHE Course Registration Portal - Setup Script
echo ============================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.10+ and try again
    pause
    exit /b 1
)

echo Python found:
python --version
echo.

REM Create virtual environment
echo Creating virtual environment...
python -m venv venv
if %errorlevel% neq 0 (
    echo ERROR: Failed to create virtual environment
    pause
    exit /b 1
)

echo Virtual environment created successfully
echo.

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo Dependencies installed successfully
echo.

REM Create .env file if it doesn't exist
if not exist .env (
    echo Creating .env file from template...
    copy env.example .env
    echo Please edit .env file with your settings
    echo.
)

REM Run migrations
echo Running migrations...
python manage.py migrate
if %errorlevel% neq 0 (
    echo ERROR: Failed to run migrations
    pause
    exit /b 1
)

echo Migrations completed successfully
echo.

REM Ask if user wants to create superuser
echo Do you want to create a superuser now? (Y/N)
set /p create_superuser=
if /i "%create_superuser%"=="Y" (
    echo.
    python manage.py createsuperuser
)

REM Ask if user wants to setup initial data
echo.
echo Do you want to setup initial CRP data? (Y/N)
set /p setup_data=
if /i "%setup_data%"=="Y" (
    echo.
    python manage.py setup_crp
)

echo.
echo ============================================
echo Setup completed successfully!
echo ============================================
echo.
echo To start the development server:
echo 1. Activate virtual environment: venv\Scripts\activate.bat
echo 2. Run server: python manage.py runserver
echo 3. Open browser: http://127.0.0.1:8000/crp/
echo.
echo Admin panel: http://127.0.0.1:8000/admin/
echo.
pause

#!/bin/bash
# ============================================================
# Vietnam Customs Data Scraper - Automated Setup Script (Linux/Mac)
# ============================================================
# This script automates the setup process for a new machine:
# 1. Creates Python virtual environment (venv)
# 2. Activates the virtual environment
# 3. Upgrades pip to latest version
# 4. Installs all dependencies from requirements.txt
#
# Usage: bash setup.sh
#        or: chmod +x setup.sh && ./setup.sh
# ============================================================

echo ""
echo "============================================================"
echo " Vietnam Customs Data Scraper - Setup Script"
echo "============================================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed!"
    echo "Please install Python 3.8+ from your package manager:"
    echo "  Ubuntu/Debian: sudo apt-get install python3 python3-venv python3-pip"
    echo "  macOS: brew install python3"
    exit 1
fi

echo "[1/4] Checking Python version..."
python3 --version

# Check if venv already exists
if [ -d "venv" ]; then
    echo ""
    echo "[WARNING] Virtual environment 'venv' already exists!"
    read -p "Do you want to recreate it? (y/N): " RECREATE
    if [[ ! "$RECREATE" =~ ^[Yy]$ ]]; then
        echo "Skipping venv creation. Using existing environment."
    else
        echo "Removing old virtual environment..."
        rm -rf venv
        
        echo ""
        echo "[2/4] Creating virtual environment..."
        python3 -m venv venv
        if [ $? -ne 0 ]; then
            echo "[ERROR] Failed to create virtual environment!"
            echo "Try running: python3 -m pip install --upgrade pip"
            exit 1
        fi
        echo "[SUCCESS] Virtual environment created successfully!"
    fi
else
    echo ""
    echo "[2/4] Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create virtual environment!"
        echo "Try running: python3 -m pip install --upgrade pip"
        exit 1
    fi
    echo "[SUCCESS] Virtual environment created successfully!"
fi

echo ""
echo "[3/4] Activating virtual environment..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to activate virtual environment!"
    exit 1
fi

echo "[SUCCESS] Virtual environment activated!"
echo ""
echo "[4/4] Installing dependencies from requirements.txt..."
python -m pip install --upgrade pip
if [ $? -ne 0 ]; then
    echo "[WARNING] Failed to upgrade pip, continuing anyway..."
fi

pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo ""
    echo "[ERROR] Failed to install dependencies!"
    echo "Please check requirements.txt and your internet connection."
    exit 1
fi

echo ""
echo "============================================================"
echo " Setup Complete!"
echo "============================================================"
echo ""
echo "Virtual environment is ready at: $(pwd)/venv"
echo ""
echo "Next steps:"
echo "  1. Configure your credentials in src/config.py"
echo "  2. Activate the environment: source venv/bin/activate"
echo "  3. Run the scraper: python run.py"
echo ""
echo "============================================================"

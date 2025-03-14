#!/bin/bash
# Setup script for AutoPDF Bot

# Exit on error
set -e

echo "🚀 Setting up AutoPDF Bot..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# Install requirements
echo "📚 Installing dependencies..."
pip install -r requirements.txt

# Create necessary directories
echo "📂 Creating directories..."
mkdir -p templates
mkdir -p generated

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "🔑 Creating .env file..."
    cp .env.example .env
    echo "⚠️ Please edit .env file with your tokens and credentials."
fi

# Create template if it doesn't exist
if [ ! -f "templates/invoice_template.pdf" ]; then
    echo "📄 Creating invoice template..."
    python create_template.py
    echo "✅ Template created!"
else
    echo "📄 Invoice template already exists."
fi

echo "
╔═══════════════════════════════════════════╗
║                                           ║
║   AutoPDF Bot setup complete!             ║
║                                           ║
║   Next steps:                             ║
║   1. Edit .env with your Telegram token   ║
║   2. Add Google credentials JSON file     ║
║   3. Run the bot with:                    ║
║      python autopdf_bot.py                ║
║                                           ║
╚═══════════════════════════════════════════╝
" 
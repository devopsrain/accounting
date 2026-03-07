#!/usr/bin/env python3

import os
import sys
from pathlib import Path

# Add the project root AND web/ directory to Python path
# web/ is needed because app.py does bare imports like 'from tenant_data_store import ...'
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web'))

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = project_root / '.env'
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"Loaded environment from: {env_path}")
    else:
        print(f"Warning: .env file not found at {env_path}")
except ImportError:
    print("Warning: python-dotenv not installed, skipping .env loading")

# Set any missing environment variables with defaults
os.environ.setdefault('FLASK_SECRET_KEY', 'production-secret-key-2026')
os.environ.setdefault('DEFAULT_ADMIN_PASSWORD', 'Admin2026!Secure') 
os.environ.setdefault('DEFAULT_HR_PASSWORD', 'HR2026!Secure')
os.environ.setdefault('DEFAULT_ACCOUNTANT_PASSWORD', 'Acc2026!Secure')
os.environ.setdefault('DEFAULT_EMPLOYEE_PASSWORD', 'Emp2026!Secure')
os.environ.setdefault('DEFAULT_DATA_ENTRY_PASSWORD', 'Data2026!Secure')

# Import the Flask app
from web.app import app

if __name__ == '__main__':
    # This will only run if called directly (not via gunicorn)
    app.run(host='0.0.0.0', port=5000, debug=False)
#!/bin/bash

# Update system
apt-get update -y
apt-get upgrade -y

# Install required packages
apt-get install -y python3 python3-pip python3-venv nginx git postgresql-client-14 supervisor

# Create application user
useradd -m -s /bin/bash businessapp
usermod -aG sudo businessapp

# Create application directory
mkdir -p /opt/ethiopian-business
chown businessapp:businessapp /opt/ethiopian-business

# Clone application (you'll need to replace with your repository URL)
cd /opt/ethiopian-business
git clone https://github.com/yourusername/accounting.git .
chown -R businessapp:businessapp /opt/ethiopian-business

# Create Python virtual environment
sudo -u businessapp python3 -m venv venv
sudo -u businessapp /opt/ethiopian-business/venv/bin/pip install --upgrade pip

# Install Python dependencies
sudo -u businessapp /opt/ethiopian-business/venv/bin/pip install -r requirements.txt
sudo -u businessapp /opt/ethiopian-business/venv/bin/pip install gunicorn psycopg2-binary

# Create environment configuration
cat > /opt/ethiopian-business/.env << EOF
FLASK_ENV=production
FLASK_DEBUG=False
SECRET_KEY=your-super-secret-key-change-this
DATABASE_URL=postgresql://${db_username}:${db_password}@${db_host}:5432/${db_name}
AWS_DEFAULT_REGION=af-south-1
EOF

chown businessapp:businessapp /opt/ethiopian-business/.env
chmod 600 /opt/ethiopian-business/.env

# Create production configuration file
cat > /opt/ethiopian-business/config.py << 'EOF'
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    DATABASE_URL = os.environ.get('DATABASE_URL')
    FLASK_ENV = os.environ.get('FLASK_ENV', 'production')
    
class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    
class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': ProductionConfig
}
EOF

# Create application startup script
cat > /opt/ethiopian-business/run_production.py << 'EOF'
#!/usr/bin/env python3
import os
from web.app import create_app
from config import config

config_name = os.getenv('FLASK_ENV', 'production')
app = create_app(config[config_name])

@app.route('/health')
def health_check():
    return {'status': 'healthy', 'service': 'Ethiopian Business Management System'}, 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
EOF

chown businessapp:businessapp /opt/ethiopian-business/run_production.py
chmod +x /opt/ethiopian-business/run_production.py

# Configure Supervisor for process management
cat > /etc/supervisor/conf.d/ethiopian-business.conf << EOF
[program:ethiopian-business]
command=/opt/ethiopian-business/venv/bin/gunicorn --bind 0.0.0.0:5000 --workers 3 --timeout 120 run_production:app
directory=/opt/ethiopian-business
user=businessapp
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/ethiopian-business.log
environment=PATH="/opt/ethiopian-business/venv/bin"
EOF

# Configure Nginx
cat > /etc/nginx/sites-available/ethiopian-business << 'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    location /static {
        alias /opt/ethiopian-business/web/static;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location /health {
        proxy_pass http://127.0.0.1:5000/health;
        access_log off;
    }
}
EOF

# Enable Nginx site
ln -sf /etc/nginx/sites-available/ethiopian-business /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Test Nginx configuration
nginx -t

# Install Python dependencies for database setup
sudo -u businessapp /opt/ethiopian-business/venv/bin/pip install python-dotenv

# Wait for database to be ready
echo "Waiting for database to be ready..."
while ! pg_isready -h ${db_host} -p 5432 -U ${db_username}; do
    echo "Waiting for database..."
    sleep 10
done

# Initialize database (you'll need to create this script)
cd /opt/ethiopian-business
sudo -u businessapp /opt/ethiopian-business/venv/bin/python3 << 'EOF'
import os
import sys
sys.path.append('/opt/ethiopian-business')

try:
    from core.ledger import GeneralLedger
    from models.vat_portal import VATContextManager
    
    # Initialize the database schema and default data
    print("Setting up database...")
    
    # Create ledger and setup standard accounts
    ledger = GeneralLedger()
    ledger.create_standard_chart_of_accounts()
    
    # Initialize VAT system
    vat_manager = VATContextManager('demo_company')
    
    print("Database initialization completed successfully!")
    
except Exception as e:
    print(f"Database initialization failed: {e}")
    sys.exit(1)
EOF

# Create log rotation for application logs
cat > /etc/logrotate.d/ethiopian-business << 'EOF'
/var/log/ethiopian-business.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    create 644 businessapp businessapp
    postrotate
        supervisorctl restart ethiopian-business
    endscript
}
EOF

# Set up automated backups
cat > /opt/ethiopian-business/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/backups"
DATE=$(date +%Y%m%d_%H%M%S)
DB_BACKUP_FILE="ethiopian_business_$DATE.sql"

mkdir -p $BACKUP_DIR

# Database backup
PGPASSWORD=${db_password} pg_dump -h ${db_host} -U ${db_username} -d ${db_name} > $BACKUP_DIR/$DB_BACKUP_FILE

# Compress backup
gzip $BACKUP_DIR/$DB_BACKUP_FILE

# Keep only last 7 days of backups
find $BACKUP_DIR -name "*.gz" -mtime +7 -delete

echo "Backup completed: $BACKUP_DIR/$DB_BACKUP_FILE.gz"
EOF

chmod +x /opt/ethiopian-business/backup.sh
chown businessapp:businessapp /opt/ethiopian-business/backup.sh

# Add daily backup to cron
echo "0 2 * * * /opt/ethiopian-business/backup.sh" | crontab -u businessapp -

# Create systemd service for additional reliability
cat > /etc/systemd/system/ethiopian-business.service << 'EOF'
[Unit]
Description=Ethiopian Business Management System
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=forking
User=businessapp
Group=businessapp
WorkingDirectory=/opt/ethiopian-business
Environment="PATH=/opt/ethiopian-business/venv/bin"
ExecStart=/opt/ethiopian-business/venv/bin/gunicorn --bind 0.0.0.0:5000 --workers 3 --daemon run_production:app
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Start and enable services
systemctl daemon-reload
systemctl enable nginx
systemctl enable supervisor
systemctl enable ethiopian-business

# Start services
systemctl start supervisor
systemctl restart nginx

# Update supervisor and start application
supervisorctl reread
supervisorctl update
supervisorctl start ethiopian-business

# Install and configure fail2ban for security
apt-get install -y fail2ban

cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = ssh
logpath = /var/log/auth.log

[nginx-http-auth]
enabled = true
filter = nginx-http-auth
logpath = /var/log/nginx/error.log
maxretry = 3
EOF

systemctl enable fail2ban
systemctl start fail2ban

# Set up CloudWatch monitoring
curl https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb -O
dpkg -i amazon-cloudwatch-agent.deb

# Basic CloudWatch configuration
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << 'EOF'
{
    "metrics": {
        "namespace": "Ethiopian-Business-MVP",
        "metrics_collected": {
            "cpu": {
                "measurement": ["cpu_usage_idle", "cpu_usage_iowait", "cpu_usage_user", "cpu_usage_system"],
                "metrics_collection_interval": 60
            },
            "disk": {
                "measurement": ["used_percent"],
                "metrics_collection_interval": 60,
                "resources": ["*"]
            },
            "mem": {
                "measurement": ["mem_used_percent"],
                "metrics_collection_interval": 60
            }
        }
    },
    "logs": {
        "logs_collected": {
            "files": {
                "collect_list": [
                    {
                        "file_path": "/var/log/ethiopian-business.log",
                        "log_group_name": "ethiopian-business-logs",
                        "log_stream_name": "{instance_id}"
                    },
                    {
                        "file_path": "/var/log/nginx/access.log",
                        "log_group_name": "nginx-access-logs",
                        "log_stream_name": "{instance_id}"
                    }
                ]
            }
        }
    }
}
EOF

# Display completion message
echo "==================================="
echo "Ethiopian Business Management System"
echo "Deployment completed successfully!"
echo "==================================="
echo "Database Host: ${db_host}"
echo "Database Name: ${db_name}"
echo "Application Status: Check with 'supervisorctl status'"
echo "Logs: /var/log/ethiopian-business.log"
echo "==================================="
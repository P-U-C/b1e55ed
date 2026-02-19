# Deployment

Production deployment guide for b1e55ed.

## Deployment Options

### Option 1: Standalone Server (Recommended)

Single VPS running all components:
- Brain cycle (cron)
- API server
- Dashboard
- Database (SQLite)

**Pros:** Simple, low-cost, no network latency  
**Cons:** Single point of failure

### Option 2: Distributed

Components on separate hosts:
- Brain + Database (compute-optimized)
- API + Dashboard (web-facing)

**Pros:** Scalable, isolated failure domains  
**Cons:** More complex, network latency

### Option 3: Serverless

API/Dashboard serverless, Brain on scheduled compute (GitHub Actions, AWS Lambda)

**Pros:** Auto-scaling, pay-per-use  
**Cons:** Cold starts, stateful database tricky

## Recommended Stack

**For $8K-$1M portfolio:** Option 1 (Standalone)

- **Provider:** DigitalOcean, Hetzner, or AWS Lightsail
- **Instance:** 2 vCPU, 4GB RAM ($12-20/month)
- **OS:** Ubuntu 22.04 LTS
- **Storage:** 20GB SSD (database grows ~1GB/month)

## Setup Guide (Ubuntu)

### 1. Provision Server

```bash
# SSH into your server
ssh root@your-server-ip

# Update system
apt update && apt upgrade -y

# Install dependencies
apt install -y git curl build-essential sqlite3

# Install Python 3.12
apt install -y python3.12 python3.12-venv python3-pip

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
```

### 2. Create Service User

```bash
# Don't run as root
useradd -m -s /bin/bash b1e55ed
su - b1e55ed
```

### 3. Clone & Install

```bash
# Clone repo (or copy wheel)
git clone https://github.com/P-U-C/b1e55ed.git
cd b1e55ed

# Install with uv
uv sync --extra dev

# Generate identity
export B1E55ED_MASTER_PASSWORD="your-secure-password"
uv run b1e55ed setup
```

### 4. Configure

```bash
# Create production config
cp config/default.yaml config/production.yaml

# Edit for your needs
vim config/production.yaml

# Set environment variables
cat >> ~/.bashrc << EOF
export B1E55ED_MASTER_PASSWORD="your-secure-password"
export B1E55ED_EXECUTION__MODE="live"  # or "paper"
export B1E55ED_HYPERLIQUID_API_KEY="..."
export B1E55ED_HYPERLIQUID_SECRET="..."
EOF

source ~/.bashrc
```

### 5. Setup Systemd Services

**API Service:**

```bash
sudo tee /etc/systemd/system/b1e55ed-api.service << EOF
[Unit]
Description=b1e55ed API Server
After=network.target

[Service]
Type=simple
User=b1e55ed
WorkingDirectory=/home/b1e55ed/b1e55ed
Environment="PATH=/home/b1e55ed/.cargo/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/home/b1e55ed/.env
ExecStart=/home/b1e55ed/.cargo/bin/uv run b1e55ed api --host 0.0.0.0 --port 5050
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

**Dashboard Service:**

```bash
sudo tee /etc/systemd/system/b1e55ed-dashboard.service << EOF
[Unit]
Description=b1e55ed Dashboard
After=network.target b1e55ed-api.service

[Service]
Type=simple
User=b1e55ed
WorkingDirectory=/home/b1e55ed/b1e55ed
Environment="PATH=/home/b1e55ed/.cargo/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/home/b1e55ed/.env
ExecStart=/home/b1e55ed/.cargo/bin/uv run b1e55ed dashboard --host 0.0.0.0 --port 5051
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

**Enable & Start:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable b1e55ed-api b1e55ed-dashboard
sudo systemctl start b1e55ed-api b1e55ed-dashboard

# Check status
sudo systemctl status b1e55ed-api
sudo systemctl status b1e55ed-dashboard
```

### 6. Setup Cron (Brain Cycles)

```bash
# Brain runs every 5 minutes
crontab -e

# Add:
*/5 * * * * cd /home/b1e55ed/b1e55ed && /home/b1e55ed/.cargo/bin/uv run b1e55ed brain >> /home/b1e55ed/logs/brain.log 2>&1
```

### 7. Reverse Proxy (Nginx)

```bash
sudo apt install -y nginx

sudo tee /etc/nginx/sites-available/b1e55ed << EOF
server {
    listen 80;
    server_name your-domain.com;

    # Dashboard
    location / {
        proxy_pass http://127.0.0.1:5051;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    # API
    location /api/ {
        proxy_pass http://127.0.0.1:5050/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/b1e55ed /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 8. SSL/TLS (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

## Security Hardening

### 1. Firewall

```bash
sudo ufw allow ssh
sudo ufw allow http
sudo ufw allow https
sudo ufw enable
```

### 2. SSH Key-Only Auth

```bash
# Disable password auth
sudo vim /etc/ssh/sshd_config
# Set: PasswordAuthentication no

sudo systemctl restart sshd
```

### 3. Secrets Management

```bash
# Store secrets in .env (not in git)
cat > /home/b1e55ed/.env << EOF
B1E55ED_MASTER_PASSWORD=your-secure-password
B1E55ED_HYPERLIQUID_API_KEY=...
B1E55ED_HYPERLIQUID_SECRET=...
B1E55ED_API__AUTH_TOKEN=bearer-token-here
EOF

chmod 600 /home/b1e55ed/.env
```

### 4. Database Backups

```bash
# Daily backup to S3/B2
cat > /home/b1e55ed/backup.sh << EOF
#!/bin/bash
DATE=\$(date +%Y%m%d)
sqlite3 /home/b1e55ed/b1e55ed/data/brain.db ".backup /tmp/brain-\$DATE.db"
gzip /tmp/brain-\$DATE.db
# Upload to S3/B2
aws s3 cp /tmp/brain-\$DATE.db.gz s3://your-bucket/backups/
rm /tmp/brain-\$DATE.db.gz
EOF

chmod +x /home/b1e55ed/backup.sh

# Add to cron
crontab -e
# Add: 0 3 * * * /home/b1e55ed/backup.sh
```

## Monitoring

### Logs

```bash
# Service logs
sudo journalctl -u b1e55ed-api -f
sudo journalctl -u b1e55ed-dashboard -f

# Brain logs
tail -f /home/b1e55ed/logs/brain.log
```

### Health Checks

```bash
# API health
curl http://localhost:5050/health

# Expected:
# {"status":"ok","uptime_seconds":123.4}
```

### Alerts

Use UptimeRobot, Pingdom, or custom script:

```bash
# Simple alert script
cat > /home/b1e55ed/alert.sh << EOF
#!/bin/bash
if ! curl -s http://localhost:5050/health | grep -q "ok"; then
    # Send alert (email, Telegram, Discord, etc.)
    echo "API DOWN" | mail -s "b1e55ed Alert" you@example.com
fi
EOF

# Run every 5 min
# crontab: */5 * * * * /home/b1e55ed/alert.sh
```

## Scaling

### When to Scale

- Brain cycle takes >2 min (should be <30s)
- API latency >500ms (should be <100ms)
- Database size >10GB (consider PostgreSQL)
- Trading >$10M (consider distributed architecture)

### Vertical Scaling (Easier)

```bash
# Upgrade instance to 4 vCPU, 8GB RAM
# Usually solves performance issues
```

### Horizontal Scaling

- **Read replicas:** SQLite → PostgreSQL with replicas
- **Load balancer:** Multiple API/Dashboard instances behind nginx
- **Distributed brain:** Partition symbols across workers

## Disaster Recovery

### Recovery Time Objective (RTO)

Target: < 1 hour to restore service

1. Spin up new server
2. Restore latest database backup
3. Deploy code
4. Restart services

### Recovery Point Objective (RPO)

Target: < 24 hours of data loss

- Daily database backups
- Optional: hourly backups for high-frequency trading

### Disaster Scenarios

**Database corruption:**
```bash
# Restore from backup
cp /path/to/backup/brain-20260218.db.gz .
gunzip brain-20260218.db.gz
cp brain-20260218.db data/brain.db
sudo systemctl restart b1e55ed-api
```

**Server down:**
- Use backup server or failover to new VPS
- Restore database from S3/B2
- Redeploy code

**Identity lost:**
```bash
# CRITICAL: Regenerate identity loses event chain integrity
# Only use as last resort
export B1E55ED_MASTER_PASSWORD="your-password"
uv run b1e55ed setup --force
```

## Cost Estimates

| Component | Monthly Cost |
|-----------|--------------|
| VPS (2vCPU, 4GB) | $12-20 |
| Bandwidth | $0-5 |
| Backups (100GB) | $2-5 |
| Domain + SSL | $1-2/yr |
| **Total** | **~$15-30/month** |

For $8K-$1M portfolio, infrastructure cost is negligible (0.02-0.45% annually).

## Production Checklist

Before going live:

- [ ] Paper trading tested for 7+ days
- [ ] Database backups automated
- [ ] Secrets stored securely (not in git)
- [ ] Services restart on failure
- [ ] Firewall configured
- [ ] SSL/TLS enabled
- [ ] Health checks/alerts active
- [ ] Logs monitored
- [ ] Kill switch tested
- [ ] Emergency contact reachable

## Next Steps

- [Configuration](configuration.md) - Production config options
- [API Reference](api-reference.md) - Monitoring endpoints
- [Getting Started](getting-started.md) - Initial setup

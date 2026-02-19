# Docker Deployment

Run b1e55ed in containers with Docker Compose.

## Quick Start

```bash
# 1. Clone repository
git clone https://github.com/P-U-C/b1e55ed.git
cd b1e55ed

# 2. Create environment file
cp .env.template .env

# 3. Edit .env (required: B1E55ED_MASTER_PASSWORD)
vim .env

# 4. Start services
docker-compose up -d

# 5. Check status
docker-compose ps
docker-compose logs -f

# 6. Access
# API:       http://localhost:5050/health
# Dashboard: http://localhost:5051
```

## Services

The stack includes 3 containers:

### 1. API (b1e55ed-api)
- REST API server
- Port: 5050
- Health: `curl http://localhost:5050/health`

### 2. Dashboard (b1e55ed-dashboard)
- Web interface
- Port: 5051
- URL: `http://localhost:5051`

### 3. Brain (b1e55ed-brain)
- Trading logic cycle
- Runs every 5 minutes
- Logs: `docker-compose logs -f brain`

## Configuration

### Environment Variables

Edit `.env` file:

```bash
# Required
B1E55ED_MASTER_PASSWORD=your-secure-password

# Execution mode
B1E55ED_EXECUTION__MODE=paper  # or 'live'

# Optional: API keys
B1E55ED_ALLIUM_API_KEY=...
B1E55ED_NANSEN_API_KEY=...

# Optional: Exchange credentials (for live mode)
B1E55ED_HYPERLIQUID_API_KEY=...
B1E55ED_HYPERLIQUID_SECRET=...

# Optional: API authentication
B1E55ED_API__AUTH_TOKEN=...
```

### Config Files

Place custom config in `config/user.yaml`:

```yaml
preset: balanced

universe:
  symbols: ["BTC", "ETH", "SOL"]

weights:
  curator: 0.30
  onchain: 0.25
  tradfi: 0.20
  social: 0.15
  technical: 0.05
  events: 0.05

execution:
  mode: paper
```

Changes take effect on container restart.

## Volumes

Data persists in Docker volumes:

```bash
# List volumes
docker volume ls | grep b1e55ed

# Inspect database
docker-compose exec api sqlite3 /data/brain.db ".tables"

# Backup database
docker-compose exec api sqlite3 /data/brain.db ".backup /data/backup.db"
docker cp b1e55ed-api:/data/backup.db ./backup-$(date +%Y%m%d).db
```

## Management

### Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f api
docker-compose logs -f dashboard
docker-compose logs -f brain

# Brain cycle logs
docker-compose exec api tail -f /logs/brain.log
```

### Restart

```bash
# All services
docker-compose restart

# Single service
docker-compose restart api
```

### Stop/Start

```bash
# Stop all
docker-compose stop

# Start all
docker-compose start

# Down (removes containers but keeps volumes)
docker-compose down

# Down + remove volumes (⚠️ deletes data)
docker-compose down -v
```

### Shell Access

```bash
# API container
docker-compose exec api bash

# Run brain cycle manually
docker-compose exec api b1e55ed brain
```

## Production Deployment

### Reverse Proxy (Nginx)

```nginx
# /etc/nginx/sites-available/b1e55ed
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5051;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:5050/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### SSL/TLS

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Get certificate
sudo certbot --nginx -d your-domain.com
```

### Auto-restart on Boot

```bash
# Enable Docker service
sudo systemctl enable docker

# Containers auto-restart (already configured in docker-compose.yml)
# restart: unless-stopped
```

## Monitoring

### Health Checks

```bash
# API health
curl http://localhost:5050/health

# Dashboard (should return HTML)
curl -I http://localhost:5051

# Docker health status
docker-compose ps
```

### Resource Usage

```bash
# Container stats
docker stats

# Disk usage
docker system df
```

## Troubleshooting

### Services won't start

```bash
# Check logs
docker-compose logs

# Rebuild images
docker-compose build --no-cache
docker-compose up -d
```

### Database locked

```bash
# Stop all services
docker-compose down

# Remove lock files
docker-compose exec api rm -f /data/brain.db-shm /data/brain.db-wal

# Restart
docker-compose up -d
```

### Permission errors

```bash
# Fix ownership (run on host)
sudo chown -R 1000:1000 data/ logs/
```

### Out of disk space

```bash
# Clean up old images
docker system prune -a

# Remove old logs
docker-compose exec api find /logs -name "*.log" -mtime +7 -delete
```

## Updates

### Update to latest version

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker-compose build
docker-compose up -d

# Check version
docker-compose exec api b1e55ed --version
```

### Rollback

```bash
# Checkout previous version
git checkout v1.0.0-beta.1

# Rebuild
docker-compose build
docker-compose up -d
```

## Security

### Secrets

- Store secrets in `.env` (not in git)
- Never commit `.env` or API keys
- Use strong master password
- Rotate credentials regularly

### Network

```bash
# Run on internal network only
# Remove port mappings from docker-compose.yml
# Access via reverse proxy on host

# Or use Docker network isolation
docker network create b1e55ed-internal
# Update docker-compose.yml networks section
```

### Backups

```bash
# Daily backup script
#!/bin/bash
DATE=$(date +%Y%m%d)
docker-compose exec -T api sqlite3 /data/brain.db ".backup /tmp/backup-$DATE.db"
docker cp b1e55ed-api:/tmp/backup-$DATE.db ./backups/
gzip ./backups/backup-$DATE.db

# Cron: 0 3 * * * /path/to/backup.sh
```

## Next Steps

- [Getting Started](docs/getting-started.md) - Detailed setup
- [Configuration](docs/configuration.md) - Customize settings
- [API Reference](docs/api-reference.md) - REST endpoints
- [Deployment](docs/deployment.md) - Production hosting

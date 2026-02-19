#!/bin/bash
set -e

# b1e55ed Installation Script
# Tested on: Ubuntu 22.04 LTS
# Usage: curl -fsSL https://raw.githubusercontent.com/P-U-C/b1e55ed/main/scripts/install.sh | bash

VERSION="1.0.0-beta.1"
INSTALL_DIR="/opt/b1e55ed"
SERVICE_USER="b1e55ed"
CONFIG_DIR="/etc/b1e55ed"
DATA_DIR="/var/lib/b1e55ed"
LOG_DIR="/var/log/b1e55ed"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    error "Please run as root (use sudo)"
fi

info "Installing b1e55ed v${VERSION}..."

# Detect OS
if [ -f /etc/os-release ]; then
    # shellcheck source=/dev/null
    . /etc/os-release
    OS=$ID
else
    error "Cannot detect OS. Only Ubuntu/Debian supported."
fi

if [[ "$OS" != "ubuntu" && "$OS" != "debian" ]]; then
    error "Unsupported OS: $OS. Only Ubuntu/Debian supported."
fi

# Update system
info "Updating system packages..."
apt-get update -qq

# Install dependencies
info "Installing dependencies..."
apt-get install -y -qq \
    curl \
    git \
    sqlite3 \
    python3.12 \
    python3.12-venv \
    python3-pip \
    build-essential \
    ca-certificates

# Install uv
if ! command -v uv &> /dev/null; then
    info "Installing uv package manager..."
    curl -fsSL https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
else
    info "uv already installed"
fi

# Create service user
if ! id "$SERVICE_USER" &>/dev/null; then
    info "Creating service user: $SERVICE_USER"
    useradd -r -s /bin/bash -d "$INSTALL_DIR" -m "$SERVICE_USER"
else
    info "Service user already exists"
fi

# Create directories
info "Creating directories..."
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" "$DATA_DIR" "$LOG_DIR"
chmod 750 "$CONFIG_DIR"

# Download/clone repo
info "Downloading b1e55ed..."
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation..."
    cd "$INSTALL_DIR"
    sudo -u "$SERVICE_USER" git pull origin main
else
    info "Cloning repository..."
    sudo -u "$SERVICE_USER" git clone https://github.com/P-U-C/b1e55ed.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    sudo -u "$SERVICE_USER" git checkout "v${VERSION}" 2>/dev/null || warn "Version tag not found, using main"
fi

# Install Python dependencies
info "Installing Python dependencies..."
sudo -u "$SERVICE_USER" bash -c "source /root/.cargo/env && uv sync"

# Interactive configuration
info "=== Configuration Setup ==="

# Master password
read -rsp "Enter master password for identity encryption: " MASTER_PASSWORD
echo
read -rsp "Confirm master password: " MASTER_PASSWORD_CONFIRM
echo

if [ "$MASTER_PASSWORD" != "$MASTER_PASSWORD_CONFIRM" ]; then
    error "Passwords do not match"
fi

# Execution mode
echo
read -rp "Execution mode (paper/live) [paper]: " EXEC_MODE
EXEC_MODE=${EXEC_MODE:-paper}

# Create .env file
info "Creating environment file..."
cat > /etc/b1e55ed/.env << EOF
B1E55ED_MASTER_PASSWORD=$MASTER_PASSWORD
B1E55ED_EXECUTION__MODE=$EXEC_MODE
EOF

chmod 600 /etc/b1e55ed/.env
chown "$SERVICE_USER:$SERVICE_USER" /etc/b1e55ed/.env

# Optional API keys
echo
read -rp "Do you have API keys to configure? (y/n) [n]: " CONFIGURE_KEYS
if [[ "$CONFIGURE_KEYS" =~ ^[Yy]$ ]]; then
    read -rp "Allium API key (optional): " ALLIUM_KEY
    read -rp "Nansen API key (optional): " NANSEN_KEY
    
    if [ -n "$ALLIUM_KEY" ]; then
        echo "B1E55ED_ALLIUM_API_KEY=$ALLIUM_KEY" >> /etc/b1e55ed/.env
    fi
    if [ -n "$NANSEN_KEY" ]; then
        echo "B1E55ED_NANSEN_API_KEY=$NANSEN_KEY" >> /etc/b1e55ed/.env
    fi
fi

# Generate identity
info "Generating node identity..."
sudo -u "$SERVICE_USER" bash -c "cd $INSTALL_DIR && source /root/.cargo/env && export B1E55ED_MASTER_PASSWORD='$MASTER_PASSWORD' && uv run b1e55ed setup"

# Create systemd services
info "Creating systemd services..."

# API service
cat > /etc/systemd/system/b1e55ed-api.service << EOF
[Unit]
Description=b1e55ed API Server
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=/etc/b1e55ed/.env
ExecStart=/root/.cargo/bin/uv run b1e55ed api --host 0.0.0.0 --port 5050
Restart=always
RestartSec=10
StandardOutput=append:$LOG_DIR/api.log
StandardError=append:$LOG_DIR/api.log

[Install]
WantedBy=multi-user.target
EOF

# Dashboard service
cat > /etc/systemd/system/b1e55ed-dashboard.service << EOF
[Unit]
Description=b1e55ed Dashboard
After=network.target b1e55ed-api.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=/etc/b1e55ed/.env
Environment="B1E55ED_API_BASE_URL=http://127.0.0.1:5050"
ExecStart=/root/.cargo/bin/uv run b1e55ed dashboard --host 0.0.0.0 --port 5051
Restart=always
RestartSec=10
StandardOutput=append:$LOG_DIR/dashboard.log
StandardError=append:$LOG_DIR/dashboard.log

[Install]
WantedBy=multi-user.target
EOF

# Brain cron service
cat > /etc/systemd/system/b1e55ed-brain.service << EOF
[Unit]
Description=b1e55ed Brain Cycle
After=network.target

[Service]
Type=oneshot
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=/etc/b1e55ed/.env
ExecStart=/root/.cargo/bin/uv run b1e55ed brain
StandardOutput=append:$LOG_DIR/brain.log
StandardError=append:$LOG_DIR/brain.log
EOF

cat > /etc/systemd/system/b1e55ed-brain.timer << EOF
[Unit]
Description=b1e55ed Brain Cycle Timer
Requires=b1e55ed-brain.service

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=1s

[Install]
WantedBy=timers.target
EOF

# Reload systemd
systemctl daemon-reload

# Enable and start services
info "Enabling services..."
systemctl enable b1e55ed-api b1e55ed-dashboard b1e55ed-brain.timer

info "Starting services..."
systemctl start b1e55ed-api
sleep 2
systemctl start b1e55ed-dashboard
systemctl start b1e55ed-brain.timer

# Check status
info "Checking service status..."
sleep 3

if systemctl is-active --quiet b1e55ed-api; then
    info "✓ API service running"
else
    warn "✗ API service not running. Check logs: journalctl -u b1e55ed-api"
fi

if systemctl is-active --quiet b1e55ed-dashboard; then
    info "✓ Dashboard service running"
else
    warn "✗ Dashboard service not running. Check logs: journalctl -u b1e55ed-dashboard"
fi

if systemctl is-active --quiet b1e55ed-brain.timer; then
    info "✓ Brain timer active"
else
    warn "✗ Brain timer not active. Check logs: journalctl -u b1e55ed-brain"
fi

# Setup log rotation
info "Configuring log rotation..."
cat > /etc/logrotate.d/b1e55ed << EOF
$LOG_DIR/*.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    create 0640 $SERVICE_USER $SERVICE_USER
    sharedscripts
    postrotate
        systemctl reload b1e55ed-api b1e55ed-dashboard >/dev/null 2>&1 || true
    endscript
}
EOF

# Installation complete
echo
info "=== Installation Complete ==="
echo
echo "Services:"
echo "  API:       http://localhost:5050/health"
echo "  Dashboard: http://localhost:5051"
echo
echo "Logs:"
echo "  sudo journalctl -u b1e55ed-api -f"
echo "  sudo journalctl -u b1e55ed-dashboard -f"
echo "  sudo journalctl -u b1e55ed-brain -f"
echo "  tail -f $LOG_DIR/*.log"
echo
echo "Configuration:"
echo "  Config:  $CONFIG_DIR/"
echo "  Data:    $DATA_DIR/"
echo "  Logs:    $LOG_DIR/"
echo
echo "Management:"
echo "  sudo systemctl status b1e55ed-api"
echo "  sudo systemctl restart b1e55ed-api"
echo "  sudo systemctl stop b1e55ed-api"
echo
echo "Next steps:"
echo "  1. Review configuration: $INSTALL_DIR/config/user.yaml"
echo "  2. Check API health: curl http://localhost:5050/health"
echo "  3. Open dashboard: http://$(hostname -I | awk '{print $1}'):5051"
echo
warn "Remember: You're in $EXEC_MODE mode. No real money will be traded."
echo
info "Installation complete! 🚀"

#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  AuditForge — Enable SSH on Linux
#  Run as root (or with sudo) on the target Linux machine.
#
#  Supports: Ubuntu/Debian, RHEL/CentOS/Rocky/Alma, SUSE, Arch
# ──────────────────────────────────────────────────────────────
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${CYAN}╔═══════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   AuditForge — Enable SSH             ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════╝${NC}"
echo ""

# ── Must run as root ────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}ERROR: This script must be run as root (use sudo).${NC}"
    exit 1
fi

# ── Detect package manager ──────────────────────────────────────
detect_pkg_manager() {
    if command -v apt-get &>/dev/null; then
        echo "apt"
    elif command -v dnf &>/dev/null; then
        echo "dnf"
    elif command -v yum &>/dev/null; then
        echo "yum"
    elif command -v zypper &>/dev/null; then
        echo "zypper"
    elif command -v pacman &>/dev/null; then
        echo "pacman"
    else
        echo "unknown"
    fi
}

PKG_MGR=$(detect_pkg_manager)
echo -e "${YELLOW}[1/4] Installing OpenSSH Server (using $PKG_MGR)...${NC}"

case "$PKG_MGR" in
    apt)
        apt-get update -qq
        apt-get install -y openssh-server >/dev/null 2>&1
        ;;
    dnf)
        dnf install -y openssh-server >/dev/null 2>&1
        ;;
    yum)
        yum install -y openssh-server >/dev/null 2>&1
        ;;
    zypper)
        zypper install -y openssh >/dev/null 2>&1
        ;;
    pacman)
        pacman -S --noconfirm openssh >/dev/null 2>&1
        ;;
    *)
        echo -e "${RED}Unknown package manager. Install openssh-server manually.${NC}"
        exit 1
        ;;
esac

echo -e "  ${GREEN}✓ openssh-server installed${NC}"

# ── 2. Enable and start sshd ───────────────────────────────────
echo -e "${YELLOW}[2/4] Starting SSH service...${NC}"

systemctl enable sshd 2>/dev/null || systemctl enable ssh 2>/dev/null || true
systemctl start sshd 2>/dev/null || systemctl start ssh 2>/dev/null || true

echo -e "  ${GREEN}✓ sshd is running and enabled${NC}"

# ── 3. Firewall ────────────────────────────────────────────────
echo -e "${YELLOW}[3/4] Configuring firewall...${NC}"

if command -v ufw &>/dev/null; then
    ufw allow 22/tcp >/dev/null 2>&1
    echo -e "  ${GREEN}✓ UFW: port 22 allowed${NC}"
elif command -v firewall-cmd &>/dev/null; then
    firewall-cmd --permanent --add-service=ssh >/dev/null 2>&1
    firewall-cmd --reload >/dev/null 2>&1
    echo -e "  ${GREEN}✓ firewalld: SSH service allowed${NC}"
elif command -v iptables &>/dev/null; then
    iptables -I INPUT -p tcp --dport 22 -j ACCEPT 2>/dev/null
    echo -e "  ${GREEN}✓ iptables: port 22 allowed${NC}"
else
    echo -e "  ${YELLOW}⊘ No firewall detected — skipping${NC}"
fi

# ── 4. Verify ──────────────────────────────────────────────────
echo -e "${YELLOW}[4/4] Verifying SSH...${NC}"
echo ""

if ss -tlnp | grep -q ':22 '; then
    echo -e "  ${GREEN}✓ Port 22 is LISTENING${NC}"
else
    echo -e "  ${RED}✗ Port 22 is NOT listening${NC}"
fi

SSHD_STATUS=$(systemctl is-active sshd 2>/dev/null || systemctl is-active ssh 2>/dev/null || echo "unknown")
if [ "$SSHD_STATUS" = "active" ]; then
    echo -e "  ${GREEN}✓ sshd is ACTIVE${NC}"
else
    echo -e "  ${RED}✗ sshd status: $SSHD_STATUS${NC}"
fi

# ── Summary ────────────────────────────────────────────────────
IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "unknown")

echo ""
echo -e "${CYAN}═══════════════════════════════════════${NC}"
echo -e "  ${GREEN}SSH is ready for AuditForge!${NC}"
echo -e "${CYAN}═══════════════════════════════════════${NC}"
echo ""
echo "  IP Address : $IP_ADDR"
echo "  SSH Port   : 22"
echo ""
echo -e "  ${YELLOW}In AuditForge, set:${NC}"
echo "    IP Address       = $IP_ADDR"
echo "    Protocol         = SSH"
echo "    Port             = 22"
echo "    Username / Pass  = (your target credentials)"
echo ""
echo -e "  ${CYAN}TIP: For passwordless sudo, run:${NC}"
echo "    echo '<username> ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers.d/auditforge"
echo ""

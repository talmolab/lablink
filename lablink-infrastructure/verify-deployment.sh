#!/bin/bash
#
# LabLink Deployment Verification Script
#
# This script verifies that a LabLink deployment is fully operational.
# It adapts verification based on your configuration (DNS, SSL, etc.)
#
# Requirements:
#   - curl, nslookup (for DNS verification)
#   - AWS CLI (optional, only if verifying Route53 records)
#
# Usage:
#   ./verify-deployment.sh [domain] [ip]
#
# Examples:
#   # Verify with explicit domain and IP
#   ./verify-deployment.sh test.lablink.sleap.ai 52.10.119.234
#
#   # IP-only deployment (no DNS)
#   ./verify-deployment.sh "" 52.10.119.234
#

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
DOMAIN_NAME="${1:-}"
EXPECTED_IP="${2:-}"

# Determine SSL provider from config if available
SSL_PROVIDER="letsencrypt"
if [ -f "config/config.yaml" ]; then
    SSL_PROVIDER=$(grep -A5 "^ssl:" config/config.yaml | grep "provider:" | awk '{print $2}' | tr -d '"' 2>/dev/null || echo "letsencrypt")
fi

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}LabLink Deployment Verification${NC}"
echo -e "${BLUE}================================${NC}"
echo ""
echo -e "Domain:      ${GREEN}${DOMAIN_NAME:-N/A (IP-only)}${NC}"
echo -e "IP Address:  ${GREEN}${EXPECTED_IP}${NC}"
echo -e "SSL Provider: ${GREEN}${SSL_PROVIDER}${NC}"
echo ""

# Step 1: DNS Resolution (if domain is provided)
if [ -n "$DOMAIN_NAME" ]; then
    echo -e "${YELLOW}[1/3] Verifying DNS resolution...${NC}"

    # Wait for DNS propagation (max 5 minutes)
    MAX_WAIT=300
    WAIT_INTERVAL=10
    ELAPSED=0
    DNS_RESOLVED=false

    while [ $ELAPSED -lt $MAX_WAIT ]; do
        # Try multiple public DNS servers
        GOOGLE_IP=$(nslookup "$DOMAIN_NAME" 8.8.8.8 2>/dev/null | grep -A1 "Name:" | tail -n1 | awk '{print $2}' || echo "")

        if [ "$GOOGLE_IP" == "$EXPECTED_IP" ]; then
            echo -e "${GREEN}✓ DNS propagated successfully${NC}"
            echo -e "  $DOMAIN_NAME → $EXPECTED_IP"
            DNS_RESOLVED=true
            break
        fi

        if [ $ELAPSED -eq 0 ]; then
            echo -e "  Waiting for DNS propagation..."
        fi

        printf "  Elapsed: ${ELAPSED}s / ${MAX_WAIT}s (resolved: ${GOOGLE_IP:-NXDOMAIN})\r"
        sleep $WAIT_INTERVAL
        ELAPSED=$((ELAPSED + WAIT_INTERVAL))
    done

    echo ""

    if [ "$DNS_RESOLVED" = false ]; then
        echo -e "${YELLOW}⚠ DNS propagation delayed after ${MAX_WAIT}s${NC}"
        echo -e "  This may be normal for newly created DNS records"
        echo -e "  Try: nslookup $DOMAIN_NAME"
    fi
    echo ""
else
    echo -e "${YELLOW}[1/3] Skipping DNS verification (IP-only deployment)${NC}"
    echo ""
fi

# Step 2: HTTP Connectivity
echo -e "${YELLOW}[2/3] Verifying HTTP connectivity...${NC}"

# Wait for container to start
echo -e "  Waiting for allocator container to start (60s)..."
sleep 60

# Determine test URL
if [ -n "$DOMAIN_NAME" ]; then
    TEST_URL="http://$DOMAIN_NAME"
else
    TEST_URL="http://$EXPECTED_IP:5000"
fi

echo -e "  Testing: $TEST_URL"

# Test HTTP (max 2 minutes)
MAX_WAIT=120
WAIT_INTERVAL=10
ELAPSED=0
HTTP_OK=false

while [ $ELAPSED -lt $MAX_WAIT ]; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$TEST_URL" 2>/dev/null || echo "000")

    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "308" ] || [ "$HTTP_CODE" = "301" ]; then
        echo -e "${GREEN}✓ HTTP responding (status $HTTP_CODE)${NC}"
        HTTP_OK=true
        break
    fi

    if [ $ELAPSED -eq 0 ]; then
        echo -e "  Waiting for allocator to respond..."
    fi

    printf "  Elapsed: ${ELAPSED}s / ${MAX_WAIT}s (status: $HTTP_CODE)\r"
    sleep $WAIT_INTERVAL
    ELAPSED=$((ELAPSED + WAIT_INTERVAL))
done

echo ""

if [ "$HTTP_OK" = false ]; then
    echo -e "${RED}✗ Allocator not responding via HTTP${NC}"
    echo -e "  Check logs: ssh ubuntu@$EXPECTED_IP sudo docker logs \$(sudo docker ps -q)"
    exit 1
fi
echo ""

# Step 3: HTTPS / SSL (if Let's Encrypt is enabled and domain exists)
if [ "$SSL_PROVIDER" = "letsencrypt" ] && [ -n "$DOMAIN_NAME" ]; then
    echo -e "${YELLOW}[3/3] Verifying HTTPS and SSL certificate...${NC}"
    echo -e "  Waiting for Let's Encrypt certificate acquisition..."

    # Test HTTPS (max 3 minutes)
    MAX_WAIT=180
    WAIT_INTERVAL=10
    ELAPSED=0
    HTTPS_OK=false

    while [ $ELAPSED -lt $MAX_WAIT ]; do
        HTTPS_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://$DOMAIN_NAME" 2>/dev/null || echo "000")

        if [ "$HTTPS_CODE" = "200" ] || [ "$HTTPS_CODE" = "302" ] || [ "$HTTPS_CODE" = "301" ]; then
            echo -e "${GREEN}✓ HTTPS responding (status $HTTPS_CODE)${NC}"

            # Get certificate info
            CERT_INFO=$(echo | openssl s_client -servername "$DOMAIN_NAME" -connect "$DOMAIN_NAME:443" 2>/dev/null | openssl x509 -noout -issuer -dates 2>/dev/null || echo "")

            if [ -n "$CERT_INFO" ]; then
                echo -e "${GREEN}✓ SSL certificate obtained:${NC}"
                echo "$CERT_INFO" | sed 's/^/  /'
            fi

            HTTPS_OK=true
            break
        fi

        if [ $ELAPSED -eq 0 ]; then
            echo -e "  Waiting for SSL certificate..."
        fi

        printf "  Elapsed: ${ELAPSED}s / ${MAX_WAIT}s (status: $HTTPS_CODE)\r"
        sleep $WAIT_INTERVAL
        ELAPSED=$((ELAPSED + WAIT_INTERVAL))
    done

    echo ""

    if [ "$HTTPS_OK" = false ]; then
        echo -e "${YELLOW}⚠ SSL certificate not yet available${NC}"
        echo -e "  Caddy may still be acquiring the certificate"
        echo -e "  Check logs: ssh ubuntu@$EXPECTED_IP sudo journalctl -u caddy -f"
    fi
elif [ "$SSL_PROVIDER" = "cloudflare" ]; then
    echo -e "${YELLOW}[3/3] Skipping SSL verification (CloudFlare handles SSL)${NC}"
elif [ "$SSL_PROVIDER" = "none" ]; then
    echo -e "${YELLOW}[3/3] Skipping SSL verification (SSL disabled)${NC}"
else
    echo -e "${YELLOW}[3/3] Skipping SSL verification (no domain configured)${NC}"
fi

echo ""

# Final summary
echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}Verification Summary${NC}"
echo -e "${BLUE}================================${NC}"
echo ""
echo -e "${GREEN}✓ Deployment verification complete!${NC}"
echo ""

if [ -n "$DOMAIN_NAME" ]; then
    echo -e "Access your allocator at:"
    echo -e "  HTTP:  ${GREEN}http://${DOMAIN_NAME}${NC}"
    if [ "$SSL_PROVIDER" = "letsencrypt" ]; then
        echo -e "  HTTPS: ${GREEN}https://${DOMAIN_NAME}${NC}"
    fi
    echo ""
    echo -e "Admin dashboard:"
    if [ "$SSL_PROVIDER" != "none" ]; then
        echo -e "  ${GREEN}https://${DOMAIN_NAME}/admin${NC}"
    else
        echo -e "  ${GREEN}http://${DOMAIN_NAME}/admin${NC}"
    fi
else
    echo -e "Access your allocator at:"
    echo -e "  HTTP:  ${GREEN}http://${EXPECTED_IP}:5000${NC}"
    echo ""
    echo -e "Admin dashboard:"
    echo -e "  ${GREEN}http://${EXPECTED_IP}:5000/admin${NC}"
fi

echo ""

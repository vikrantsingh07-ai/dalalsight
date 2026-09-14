#!/usr/bin/env bash
# Set up the DalalSight backend on a fresh Ubuntu 24.04 server (a Mumbai or Bangalore region is best for NSE data).
#
#   1. Point your API domain's DNS A record at the server, so Caddy can get the HTTPS certificate.
#   2. Clone the private repo (sign in to GitHub):  git clone https://github.com/vikrantsingh07-ai/dalalsight.git /opt/dalalsight
#   3. cd /opt/dalalsight && sudo bash deploy/setup-ubuntu.sh api.yourdomain.com https://your-app.vercel.app
#
# The script installs Python 3.12 and Caddy, creates the "dalalsight" service user, installs the app into .venv, sets the
# server values in .env (generating CC_ACCESS_TOKEN if it is empty), starts the systemd service behind Caddy and runs
# the preflight check. It is safe to run again after a git pull. The dashboard origin argument is optional (leave it out
# when you open the dashboard from this server itself).
set -euo pipefail

DOMAIN="${1:?usage: sudo bash deploy/setup-ubuntu.sh <api domain> [dashboard origin, e.g. https://your-app.vercel.app]}"
ORIGIN="${2:-}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER=dalalsight
ENV_FILE="$APP_DIR/.env"

if [[ $EUID -ne 0 ]]; then
  echo "Run this with sudo." >&2
  exit 1
fi

echo "==> Installing Python 3.12 and Caddy"
apt-get update
apt-get install -y python3.12 python3.12-venv caddy

echo "==> Service user and Python environment"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
python3.12 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -e "$APP_DIR/packages/tradingagents" -e "$APP_DIR"

echo "==> Server settings in $ENV_FILE"
[[ -f "$ENV_FILE" ]] || cp "$APP_DIR/.env.example" "$ENV_FILE"
set_env() {  # set KEY=VALUE in .env, replacing an existing line
  local key="$1" value="$2"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >>"$ENV_FILE"
  fi
}
set_env CC_HOST 127.0.0.1
set_env CC_PORT 8765
set_env CC_DEV_MODE false
set_env CC_CORS_ORIGINS "$ORIGIN"
set_env LIVE_EXECUTION_ENABLED false
if [[ -z "$(grep -E '^CC_ACCESS_TOKEN=' "$ENV_FILE" | cut -d= -f2- || true)" ]]; then
  set_env CC_ACCESS_TOKEN "$(python3.12 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  echo "    Generated a new CC_ACCESS_TOKEN. The dashboard asks for it once: sudo grep CC_ACCESS_TOKEN $ENV_FILE"
fi
if [[ -z "$(grep -E '^OPENROUTER_API_KEY=' "$ENV_FILE" | cut -d= -f2- || true)" ]]; then
  echo "    OPENROUTER_API_KEY is empty: add it to $ENV_FILE for AI features, then: sudo systemctl restart dalalsight"
fi
mkdir -p "$APP_DIR/data"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
chmod 600 "$ENV_FILE"

echo "==> systemd service"
sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__USER__|$SERVICE_USER|g" "$APP_DIR/deploy/dalalsight.service" >/etc/systemd/system/dalalsight.service
systemctl daemon-reload
systemctl enable dalalsight
systemctl restart dalalsight

echo "==> Caddy (HTTPS for $DOMAIN)"
sed "s|__DOMAIN__|$DOMAIN|g" "$APP_DIR/deploy/Caddyfile" >/etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

echo "==> Preflight: can this server reach NSE, Yahoo and the AI provider?"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/python" -m cc --check || true

cat <<EOF

Done. Check the API:  curl -H "X-Access-Token: <CC_ACCESS_TOKEN>" https://$DOMAIN/api/status
Logs:                 journalctl -u dalalsight -f
After a git pull:     sudo bash deploy/setup-ubuntu.sh $DOMAIN ${ORIGIN}
EOF

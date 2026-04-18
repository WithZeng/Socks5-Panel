#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-socks5-panel}"
APP_DIR="${APP_DIR:-/opt/${APP_NAME}}"
REPO_URL="${REPO_URL:-}"
BRANCH="${BRANCH:-main}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERVICE_NAME="${SERVICE_NAME:-socks5-panel}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-5000}"

if ! command -v git >/dev/null 2>&1; then
  echo "git 未安装，请先安装 git。"
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "找不到 Python: ${PYTHON_BIN}"
  exit 1
fi

if [ ! -d "${APP_DIR}/.git" ]; then
  if [ -z "${REPO_URL}" ]; then
    echo "首次部署需要提供 REPO_URL，例如：REPO_URL=git@github.com:you/repo.git"
    exit 1
  fi

  mkdir -p "$(dirname "${APP_DIR}")"
  git clone -b "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
else
  git -C "${APP_DIR}" fetch --all --prune
  git -C "${APP_DIR}" checkout "${BRANCH}"
  git -C "${APP_DIR}" pull --ff-only origin "${BRANCH}"
fi

cd "${APP_DIR}"

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ".env 已根据示例生成，请尽快修改 SECRET_KEY 和管理员密码。"
fi

"${PYTHON_BIN}" -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

mkdir -p instance

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Socks5 Panel
After=network.target

[Service]
User=root
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/gunicorn --workers 2 --bind ${HOST}:${PORT} app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
systemctl --no-pager --full status "${SERVICE_NAME}" || true

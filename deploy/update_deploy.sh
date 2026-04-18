#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-socks5-panel}"
APP_DIR="${APP_DIR:-/opt/${APP_NAME}}"
REPO_URL="${REPO_URL:-https://github.com/WithZeng/Socks5-Panel.git}"
BRANCH="${BRANCH:-main}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERVICE_NAME="${SERVICE_NAME:-socks5-panel}"
SERVICE_USER="${SERVICE_USER:-root}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-5000}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-2}"

log() {
  printf '[deploy] %s\n' "$1"
}

require_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "请使用 root 或 sudo 运行该脚本。"
    exit 1
  fi
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "缺少命令: $1"
    exit 1
  fi
}

ensure_repo() {
  if [ ! -d "${APP_DIR}/.git" ]; then
    echo "未找到已部署仓库，请先运行 deploy/install.sh 做首次安装。"
    exit 1
  fi

  git -C "${APP_DIR}" remote set-url origin "${REPO_URL}"
  git -C "${APP_DIR}" fetch origin "${BRANCH}" --prune
  git -C "${APP_DIR}" checkout "${BRANCH}"
  git -C "${APP_DIR}" reset --hard "origin/${BRANCH}"
}

ensure_runtime_dirs() {
  mkdir -p "${APP_DIR}/instance"
  if id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"
  fi
}

ensure_env_file() {
  if [ ! -f "${APP_DIR}/.env" ]; then
    cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
    log "已生成 ${APP_DIR}/.env，请尽快修改 SECRET_KEY 和管理员账号密码。"
  fi
}

install_python_deps() {
  "${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"
  # shellcheck disable=SC1091
  source "${APP_DIR}/.venv/bin/activate"
  pip install --upgrade pip
  pip install -r "${APP_DIR}/requirements.txt"
}

write_systemd_service() {
  cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Socks5 Panel
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/gunicorn --workers ${GUNICORN_WORKERS} --bind ${HOST}:${PORT} app:app
Restart=always
RestartSec=3
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF
}

restart_service() {
  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}"
  systemctl restart "${SERVICE_NAME}"
  systemctl --no-pager --full status "${SERVICE_NAME}" || true
}

main() {
  require_root
  require_command git
  require_command "${PYTHON_BIN}"
  require_command systemctl

  log "同步仓库代码"
  ensure_repo

  log "准备运行目录和环境文件"
  ensure_runtime_dirs
  ensure_env_file

  log "安装 Python 依赖"
  install_python_deps

  log "写入 systemd 服务"
  write_systemd_service

  log "重启应用服务"
  restart_service

  log "部署完成。访问地址: http://${HOST}:${PORT}"
}

main "$@"

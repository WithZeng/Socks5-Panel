#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-socks5-panel}"
APP_DIR="${APP_DIR:-/opt/${APP_NAME}}"
REPO_URL="${REPO_URL:-https://github.com/WithZeng/Socks5-Panel.git}"
BRANCH="${BRANCH:-main}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERVICE_USER="${SERVICE_USER:-root}"

log() {
  printf '[one-click] %s\n' "$1"
}

require_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "请使用 root 或 sudo 运行此脚本。"
    exit 1
  fi
}

run_script() {
  local script_path="$1"
  APP_DIR="${APP_DIR}" \
  REPO_URL="${REPO_URL}" \
  BRANCH="${BRANCH}" \
  PYTHON_BIN="${PYTHON_BIN}" \
  SERVICE_USER="${SERVICE_USER}" \
  bash "${script_path}"
}

main() {
  require_root

  if [ -d "${APP_DIR}/.git" ]; then
    log "检测到现有部署，执行更新部署"
    run_script "${APP_DIR}/deploy/update_deploy.sh"
    exit 0
  fi

  log "未检测到部署目录，执行首次安装"
  local temp_script
  temp_script="$(mktemp)"
  curl -fsSL "${REPO_URL%/.git}/raw/${BRANCH}/deploy/install.sh" -o "${temp_script}"
  chmod +x "${temp_script}"
  APP_DIR="${APP_DIR}" \
  REPO_URL="${REPO_URL}" \
  BRANCH="${BRANCH}" \
  PYTHON_BIN="${PYTHON_BIN}" \
  SERVICE_USER="${SERVICE_USER}" \
  bash "${temp_script}"
  rm -f "${temp_script}"
}

main "$@"

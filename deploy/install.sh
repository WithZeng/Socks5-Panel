#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-socks5-panel}"
APP_DIR="${APP_DIR:-/opt/${APP_NAME}}"
REPO_URL="${REPO_URL:-https://github.com/WithZeng/Socks5-Panel.git}"
BRANCH="${BRANCH:-main}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERVICE_USER="${SERVICE_USER:-root}"

log() {
  printf '[install] %s\n' "$1"
}

require_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "请使用 root 或 sudo 运行此脚本。"
    exit 1
  fi
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

install_base_packages() {
  if has_cmd apt-get; then
    log "安装基础依赖"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y git "${PYTHON_BIN}" "${PYTHON_BIN}-venv" curl
    return
  fi

  echo "未识别的包管理器，请先手动安装 git、${PYTHON_BIN}、${PYTHON_BIN}-venv 和 curl。"
  exit 1
}

clone_or_refresh_repo() {
  mkdir -p "$(dirname "${APP_DIR}")"

  if [ -d "${APP_DIR}/.git" ]; then
    log "检测到现有仓库，切换到最新代码"
    git -C "${APP_DIR}" remote set-url origin "${REPO_URL}"
    git -C "${APP_DIR}" fetch origin "${BRANCH}" --prune
    git -C "${APP_DIR}" checkout "${BRANCH}"
    git -C "${APP_DIR}" reset --hard "origin/${BRANCH}"
    return
  fi

  if [ -d "${APP_DIR}" ] && [ -n "$(ls -A "${APP_DIR}" 2>/dev/null || true)" ]; then
    echo "目录 ${APP_DIR} 已存在且非空，无法直接克隆。"
    exit 1
  fi

  log "克隆仓库 ${REPO_URL}"
  rm -rf "${APP_DIR}"
  git clone -b "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
}

main() {
  require_root

  if ! has_cmd git || ! has_cmd "${PYTHON_BIN}" || ! has_cmd curl; then
    install_base_packages
  fi

  clone_or_refresh_repo

  log "调用更新部署脚本"
  APP_DIR="${APP_DIR}" \
  REPO_URL="${REPO_URL}" \
  BRANCH="${BRANCH}" \
  PYTHON_BIN="${PYTHON_BIN}" \
  SERVICE_USER="${SERVICE_USER}" \
  bash "${APP_DIR}/deploy/update_deploy.sh"
}

main "$@"

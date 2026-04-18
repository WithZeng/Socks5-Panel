# Socks5 Panel

一个基于 Flask 的 Socks5 转换与管理面板，保留了原始 `app.py` 的核心转换思路，并补上可持续运营需要的后台能力。

## 当前能力

- 初始 `admin` 管理员登录验证
- 多个中转服务器备选项管理
- 文本和 Excel 两种导入方式
- 每次转换保存历史记录
- 所有登记时间按中国北京时间保存
- 按国家或地区分组管理 IP
- 自动检测同一中转服务器已占用端口
- 自动建议下一段可用起始端口
- 可下载 JSON 和 Excel 结果
- 提供 Linux 首次安装和后续更新脚本

## 开发规范

本仓库后续默认按 `karpathy-guidelines` 风格开发。

- 项目约束见 [AGENTS.md](AGENTS.md)
- 说明文件见 [KARPATHY_GUIDELINES.md](KARPATHY_GUIDELINES.md)

## 输入格式

文本导入和 Excel 单元格内容都支持：

```text
1.2.3.4:1080:user:pass
1.2.3.4:1080:user:pass{remark}
```

如果没有提供 `{remark}`，系统会根据你填写的备注前缀和起始编号自动生成。

## 本地启动

### Linux / macOS

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

启动后访问 `http://127.0.0.1:5000`。

## 环境变量

参考 [.env.example](.env.example)：

```env
SECRET_KEY=change-this-secret-key
ADMIN_USERNAME=admin
ADMIN_PASSWORD=ChangeMe123!
# DATABASE_URL=sqlite:///panel.db
```

默认数据库是 Flask `instance` 目录下的 SQLite 文件。

## 默认管理员账号

- 用户名：`admin`
- 密码：`ChangeMe123!`

部署前请先修改 `.env`。

## Linux 一键部署

现在部署分成两类脚本：

- 首次安装脚本：[deploy/install.sh](deploy/install.sh)
- 更新重部署脚本：[deploy/update_deploy.sh](deploy/update_deploy.sh)

### 首次安装

在全新 Linux 服务器上，直接执行：

```bash
curl -fsSL https://raw.githubusercontent.com/WithZeng/Socks5-Panel/main/deploy/install.sh | sudo bash
```

如果你想指定分支、目录或服务用户，可以这样：

```bash
curl -fsSL https://raw.githubusercontent.com/WithZeng/Socks5-Panel/main/deploy/install.sh | \
sudo APP_DIR=/opt/socks5-panel BRANCH=main SERVICE_USER=root bash
```

首次安装脚本会自动：

1. 安装基础依赖 `git`、`python3`、`python3-venv`、`curl`
2. 直接从 GitHub 拉取仓库
3. 创建部署目录
4. 调用更新脚本完成虚拟环境、依赖、`.env`、systemd 服务配置

### 后续更新

服务器上后续更新直接执行：

```bash
sudo bash /opt/socks5-panel/deploy/update_deploy.sh
```

如果部署目录不是 `/opt/socks5-panel`，可以显式指定：

```bash
sudo APP_DIR=/your/app/path bash /your/app/path/deploy/update_deploy.sh
```

更新脚本会自动：

1. 拉取远端最新代码
2. 强制同步到远端分支最新版本
3. 更新 Python 虚拟环境和依赖
4. 保留现有 `.env`
5. 重写并重启 `systemd` 服务

## 部署后的常用命令

查看服务状态：

```bash
sudo systemctl status socks5-panel
```

重启服务：

```bash
sudo systemctl restart socks5-panel
```

查看日志：

```bash
sudo journalctl -u socks5-panel -f
```

## 手动运行方式

如果你暂时不想用 systemd，也可以手动运行：

```bash
cd /opt/socks5-panel
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
gunicorn --workers 2 --bind 0.0.0.0:5000 app:app
```

## 推送到 GitHub

仓库地址：

- [https://github.com/WithZeng/Socks5-Panel](https://github.com/WithZeng/Socks5-Panel)

如果你本地继续开发后要推送：

```bash
git add .
git commit -m "your message"
git push origin main
```

## 项目结构

```text
app.py
panel/
  __init__.py
  auth.py
  config.py
  models.py
  services.py
  views.py
templates/
static/
deploy/
  install.sh
  update_deploy.sh
  socks5-panel.service
AGENTS.md
KARPATHY_GUIDELINES.md
README.md
```

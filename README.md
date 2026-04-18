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
- 提供 Linux 一键更新部署脚本

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

## 部署方式

### 方式一：手动部署到 Linux 服务器

```bash
git clone <your-repo-url> /opt/socks5-panel
cd /opt/socks5-panel
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

如果要长期运行，推荐使用 `gunicorn + systemd`。

```bash
source .venv/bin/activate
gunicorn --workers 2 --bind 0.0.0.0:5000 app:app
```

项目已经提供了 systemd 服务模板：

- [deploy/socks5-panel.service](deploy/socks5-panel.service)

### 方式二：一键更新部署

项目内置脚本：

- [deploy/update_deploy.sh](deploy/update_deploy.sh)

首次部署：

```bash
REPO_URL=git@github.com:your-name/your-repo.git BRANCH=main bash deploy/update_deploy.sh
```

后续更新：

```bash
bash deploy/update_deploy.sh
```

这个脚本会自动：

1. clone 或 pull 最新代码
2. 创建或更新虚拟环境
3. 安装依赖
4. 生成 `.env`
5. 安装并重启 `systemd` 服务

## 推送到 GitHub

当前目录已经初始化为 Git 仓库，但还没有远端。

### 如果你已经有 GitHub 仓库

```bash
git remote add origin <your-repo-url>
git add .
git commit -m "Initial Socks5 panel"
git push -u origin main
```

### 如果你要新建 GitHub 仓库

先重新登录 GitHub CLI：

```bash
gh auth login -h github.com
```

然后执行：

```bash
git add .
git commit -m "Initial Socks5 panel"
gh repo create Socks5-Panel --source . --private --push
```

如果想公开仓库，把 `--private` 改成 `--public`。

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
AGENTS.md
KARPATHY_GUIDELINES.md
README.md
```

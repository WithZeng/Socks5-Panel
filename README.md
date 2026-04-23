# Socks5 Panel

一个基于 Flask 的 Socks5 批量转换与交付面板，负责把原始代理整理成统一交付格式，并维护中转线路、历史批次和 Zero 同步状态。

## 当前能力

- 管理员登录保护
- 文本和 Excel 两种导入方式
- 中转服务器管理与自动端口建议
- 批次历史、JSON/Excel 下载
- 国家分组与备注续号
- Zero 线路同步
- Zero 端口创建集成
- `ZERO_DRY_RUN=true` 演练模式

## 开发约束

本仓库默认遵循 `karpathy-guidelines` 风格开发。

- 项目规则见 [AGENTS.md](AGENTS.md)
- 说明见 [KARPATHY_GUIDELINES.md](KARPATHY_GUIDELINES.md)

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

ZERO_API_BASE=https://zero.withzeng.de
ZERO_API_KEY=
ZERO_API_TIMEOUT=10
ZERO_DRY_RUN=true
ZERO_DEFAULT_FORWARD_ENDPOINT_IDS=16,17
ZERO_DEFAULT_CHAIN_FIXED_HOPS_NUM=2
```

说明：

- `ZERO_DRY_RUN=true` 时，系统只记录本地批次并模拟调用 Zero，不会真正写入远端。
- `ZERO_DRY_RUN=false` 后，勾选“同步到 Zero”会真实创建端口。
- `ZERO_DEFAULT_FORWARD_ENDPOINT_IDS` 用于高级选项未选择落地节点时的默认值。

## Zero 集成流程

1. 在 `.env` 中填入 `ZERO_API_BASE` 和 `ZERO_API_KEY`
2. 保持 `ZERO_DRY_RUN=true` 先验证界面和批次结果
3. 进入“中转线路”页面执行“从 Zero 同步线路”
4. 回到控制台，选择带 `syncd` 标识的线路并勾选“同步到 Zero”
5. 确认演练结果无误后，再把 `ZERO_DRY_RUN` 改为 `false`

## 默认管理员账号

- 用户名：`admin`
- 密码：`ChangeMe123!`

部署前请先修改。

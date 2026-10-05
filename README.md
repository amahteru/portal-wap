---
title: Portal WAP
emoji: 🌐
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

# Portal WAP

老手机专用的 WAP 综合门户网站（导航 + 天气 + 新闻）。

本项目为经典功能机（如诺基亚 S40/S60、摩托罗拉、索爱等机型）打造原汁原味的 XHTML Mobile 1.0 浏览体验，同时完整兼容现代桌面与移动端浏览器。集成门户导航、实时天气查询和分类新闻聚合三大核心功能，具备双模式存储（MongoDB 持久化与纯内存优雅降级）及生产级安全加固。

---

## 🌟 功能特性

- **经典门户导航**
  - 标准 XHTML Mobile 1.0 Strict 规范，轻量极速，排版紧凑。
  - 聚合常用移动站点分类与百度搜索直达。
  - 中间跳转页自动跟踪链接点击与 UV 访客统计。
- **实时天气查询**
  - 支持全国省份与直辖市层级导航、首字母拼音快速定位及关键词实时搜索。
  - 集成 `wttr.in` 气象数据获取，提供多日预报、温湿度及风向风速。
  - 深度整合 WAQI 全球空气质量指数（AQI）及健康等级提示。
  - 浏览器 Cookie 自动记忆最近查看城市，一键直达。
- **分类新闻聚合**
  - 覆盖国内、国际、科技、财经、社会、文化、体育等 12 大主流 RSS 源。
  - 后台异步轮询拉取与缓存，低延迟秒级响应。
  - 集成 `trafilatura` 智能正文抽取与排版清理，移除杂质与广告。
  - 生产级安全图片代理：HMAC-SHA256 防篡改验签、严格 URL 域名白名单与 Pillow 智能等比缩放压缩（老机适配 240px 宽）。
- **高可用与健壮架构**
  - **双模式数据层**：配置 `MONGO_URI` 时持久化访客日志与新闻缓存；未配置或网络故障时自动优雅降级为全内存（In-Memory）运行模式。
  - **健康检查与监控**：提供 `/health` 探针与 `/admin/ips` 访客统计接口。

---

## 📂 项目目录结构

```text
portal-wap/
├── app.py                  # FastAPI 主应用入口、导航核心路由、中间件与生命周期
├── core/
│   ├── __init__.py
│   └── db.py               # MongoDB 异步驱动封装与内存降级存储引擎
├── routers/
│   ├── __init__.py
│   ├── weather.py          # 天气模块路由、城市数据检索与 AQI 解析
│   └── news.py             # 新闻模块路由、RSS 调度、正文抓取与图片防盗链代理
├── tests/
│   ├── __init__.py
│   ├── test_db.py          # 数据库与缓存模式测试
│   ├── test_nav.py         # 导航与重定向功能测试
│   ├── test_weather.py     # 天气查询与缓存测试
│   ├── test_news.py        # 新闻分类、文章读取与图片代理测试
│   └── test_e2e.py         # 全流程端到端集成测试
├── Dockerfile              # 生产环境 Docker 容器定义 (Python 3.11-slim)
├── requirements.txt        # Python 依赖清单
├── favicon.ico             # 站点图标
├── speeddial-icon.png      # 快捷拨号大图标
└── README.md               # 项目说明文档
```

---

## ⚙️ 环境变量配置

系统支持通过环境变量进行定制化部署配置：

| 变量名 | 必选/推荐 | 默认值 | 说明 |
|---|---|---|---|
| `SECRET_KEY` | **生产必填** | `portal_wap_default_secret_2026` | 用于新闻图片代理 URL 的 HMAC-SHA256 签名密钥。**生产环境务必配置自定义强密钥，切勿使用默认值！** |
| `MONGO_URI` | 可选 | 空 | MongoDB 异步连接串（支持 MongoDB Atlas 或自建实例）。未配置时系统自动降级为全内存模式。 |
| `SPACE_ID` | 可选 | `default_space` | 数据库集合前缀隔离标识，用于区分多实例或 HuggingFace Space 部署环境。 |
| `WAQI_TOKEN` | 可选 | 空 | WAQI（世界空气质量指数）平台 API Token。配置后城市天气页展示 AQI 卡片。 |

### `SECRET_KEY` 安全密钥生成指南

在生产部署前，请生成高强度随机密钥：

```bash
# 方法 1：使用 OpenSSL
openssl rand -hex 32

# 方法 2：使用 Python secrets 模块
python -c "import secrets; print(secrets.token_hex(32))"
```

将生成的 64 位十六进制字符设置到环境变量 `SECRET_KEY` 中，防止老机图片代理接口被用于未授权请求或 SSRF 探测。

---

## 🚀 本地开发与运行

### 1. 环境准备
推荐使用 Python 3.10+。

```bash
# 克隆仓库
git clone https://github.com/tzucet/portal-wap.git
cd portal-wap

# 创建虚拟环境（可选）
python -m venv venv
# Linux / macOS
source venv/bin/activate
# Windows PowerShell
.\venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt
```

### 2. 运行服务
```bash
uvicorn app:app --host 0.0.0.0 --port 7860 --reload
```

服务启动后，可在浏览器中访问：
- 首页导航：`http://localhost:7860/`
- 天气预报：`http://localhost:7860/weather`
- 资讯新闻：`http://localhost:7860/news`
- 健康检查：`http://localhost:7860/health`
- 访客统计：`http://localhost:7860/admin/ips`

### 3. 运行完整测试套件
项目配备了完整的自动化单元测试与端到端测试覆盖：

```bash
python -m unittest discover tests
```

---

## 🐳 Docker 容器化部署

### 1. 使用 Docker 构建镜像
```bash
docker build -t portal-wap .
```

### 2. 运行容器
```bash
docker run -d \
  --name portal-wap \
  -p 7860:7860 \
  -e SECRET_KEY="your-strong-random-secret-key" \
  -e MONGO_URI="mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority" \
  -e WAQI_TOKEN="your-waqi-token" \
  portal-wap
```

### 3. Hugging Face Spaces 部署
本项目完全兼容 Hugging Face Spaces Docker SDK：
1. 在 Hugging Face 创建新的 Space，SDK 类型选择 **Docker**。
2. 将本仓库代码推送到该 Space。
3. 在 Space Settings 的 **Variables and secrets** 中配置 `SECRET_KEY`、`MONGO_URI`（可选）、`WAQI_TOKEN`（可选）。
4. Space 将自动构建并在 `0.0.0.0:7860` 上线运行。

---

## 📄 授权协议

MIT License

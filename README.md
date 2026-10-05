---
title: Portal WAP
emoji: 🌐
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# Portal WAP

老手机专用的 WAP 综合门户网站（导航 + 天气 + 新闻）。

本项目为经典功能机（如诺基亚 S40/S60、摩托罗拉、索爱等机型）打造原汁原味的 XHTML Mobile 1.0 浏览体验，同时完整兼容现代桌面与移动端浏览器。集成门户导航、实时天气查询和分类新闻聚合三大核心功能，内置轻量级 SQLite WAL 持久化引擎（支持零配置即开即用与新闻长期沉淀保留）。

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
- **分类新闻聚合（长期保留）**
  - 覆盖国内、国际、科技、财经、社会、文化、体育等 12 大主流 RSS 源。
  - 后台异步轮询拉取，自动写入本地 SQLite 数据库进行长期持久化（每分类保留高达 1000 篇历史文章）。
  - 集成 `trafilatura` 智能正文抽取与排版清理，抓取后自动永久缓存，避免重复抓取与源站失效。
  - 生产级安全图片代理：HMAC-SHA256 防篡改验签与 Pillow 智能等比缩放压缩（老机适配 240px 宽），图片本地持久化缓存。
- **轻量级零配置存储**
  - **内置 SQLite (WAL 模式)**：无需安装配置任何外部数据库（如 MongoDB/MySQL），免除第三方数据库账户与网络延迟。
  - **容器与 Space 自动适配**：优先挂载 Hugging Face Spaces Persistent Storage (`/data/portal.db`)，重启不丢数据；本地开发则默认保存在项目根目录。
  - **零配置安全密钥**：未设置 `SECRET_KEY` 时自动生成安全的 32 字节高熵随机密钥，即开即用。
  - **健康检查**：提供标准 `/health` 探针接口供容器与负载均衡检测。

---

## 📂 项目目录结构

```text
portal-wap/
├── app.py                  # FastAPI 主应用入口、导航核心路由、中间件与生命周期
├── core/
│   ├── __init__.py
│   ├── db.py               # SQLite WAL 存储引擎 (访客、新闻、文章全文、图片缓存)
│   └── http.py             # 全局共享 httpx.AsyncClient 连接池管理
├── routers/
│   ├── __init__.py
│   ├── weather.py          # 天气模块路由、城市数据检索与 AQI 解析
│   └── news.py             # 新闻模块路由、RSS 调度、正文抓取与图片防盗链代理
├── Dockerfile              # 生产环境 Docker 容器定义 (Python 3.11-slim)
├── .dockerignore           # 容器构建忽略清单
├── requirements.txt        # Python 依赖清单 (精简无第三方DB依赖)
├── favicon.ico             # 站点图标
├── speeddial-icon.png      # 快捷拨号大图标
├── LICENSE                 # MIT 开源协议
└── README.md               # 项目说明文档
```

---

## ⚙️ 环境变量配置

系统遵循“零配置开箱即用”原则，所有环境变量均为可选：

| 变量名 | 必选/可选 | 默认值 | 说明 |
|---|---|---|---|
| `SECRET_KEY` | 可选 | 自动生成 32 字节随机密钥 | 用于新闻图片代理 URL 的 HMAC-SHA256 签名密钥。生产环境建议固定配置以保证重启后已签名的静态图片链接依然有效。 |
| `DATA_DIR` | 可选 | `/data`（若存在）或当前目录 | SQLite 数据库文件存放目录。在 Hugging Face Spaces 开启 Persistent Storage 后自动存入 `/data/portal.db`。 |
| `WAQI_TOKEN` | 可选 | 空 | WAQI（世界空气质量指数）平台 API Token。配置后城市天气页展示 AQI 卡片。 |

---

## 🚀 本地开发与运行

### 1. 环境准备
推荐使用 Python 3.10+。

```bash
# 克隆仓库
git clone https://github.com/amahteru/portal-wap.git
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

---

## 🐳 Docker 与 Hugging Face Spaces 部署

### 1. 使用 Docker 构建与运行
```bash
# 构建镜像
docker build -t portal-wap .

# 运行容器（可挂载数据卷实现数据永久保存）
docker run -d \
  --name portal-wap \
  -p 7860:7860 \
  -v portal_data:/data \
  -e SECRET_KEY="your-fixed-random-secret-key" \
  portal-wap
```

### 2. Hugging Face Spaces 一键部署
本项目完全原生支持 Hugging Face Spaces Docker SDK：
1. 在 Hugging Face 创建新的 Space，SDK 类型选择 **Docker**。
2. 将本仓库代码推送到该 Space。
3. （推荐）在 Space Settings 中开启 **Persistent Storage**（挂载于 `/data`），系统将自动把数据库写入 `/data/portal.db`，即使 Space 休眠或更新代码，新闻与访客数据永不丢失！
4. 在 Space Settings 的 **Variables and secrets** 中配置 `SECRET_KEY`（建议固定）与 `WAQI_TOKEN`（可选）。
5. Space 将自动完成构建并在端口 `7860` 上线运行。

---

## 📄 授权协议

MIT License

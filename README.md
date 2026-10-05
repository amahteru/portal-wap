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

为经典功能机与复古移动设备（如塞班系统、诺基亚 S40/S60、早期黑莓等）打造的轻量级 XHTML Mobile 1.0 综合门户网站（导航 + 天气 + 新闻）。

## 功能

* **经典导航**：严格遵循 XHTML Mobile 1.0 规范，提供分类站点导航与百度搜索直达。
* **实时天气**：支持全国省市检索与 `wttr.in` 气象预报，可选接入 WAQI 空气质量指数，Cookie 自动记忆常用城市。
* **分类资讯**：涵盖 12 类主流 RSS 频道，集成正文清洗与 Pillow 图片等比缩放转码（适配 240px 屏宽）。
* **安全代理**：全站图片采用 HMAC-SHA256 防篡改验签代理，重定向严格校验 Hostname 杜绝钓鱼跳转。
* **持久存储**：内置 SQLite (WAL 模式)，自动兼容本地与 Hugging Face 容器挂载卷，零配置开箱即用。

## 部署

1. 在 [Hugging Face](https://huggingface.co/) 创建新的 Space，SDK 选择 **Docker**。
2. 将本项目代码推送到该 Space 关联的 Git 仓库。
3. （可选）在 Space 设置中开启 **Persistent Storage**（挂载至 `/data`），重启不丢数据。
4. Space 将自动构建并在 `7860` 端口上线运行。

## 配置

系统遵循零配置开箱即用原则，可按需在环境变量中添加：

* **`SECRET_KEY`**：图片代理签名密钥（可选，未设置时自动生成并持久化；生产环境建议固定配置）。
* **`DATA_DIR`**：数据库存储目录（可选，默认优先使用 `/data`，否则保存在项目根目录）。
* **`WAQI_TOKEN`**：世界空气质量指数 API Token（可选，配置后天气详情展示 AQI 数据）。

## 协议

本项目基于 [MIT License](./LICENSE) 协议开源。

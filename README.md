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

为经典功能机与复古移动设备（如塞班系统、诺基亚 S40/S60、早期黑莓等）打造的 XHTML Mobile 1.0 综合门户网站。

## 功能

* **经典导航**：遵循 XHTML Mobile 1.0 规范，提供分类站点导航与搜索直达。
* **实时天气**：支持全国省市检索与 `wttr.in` 气象预报，可选接入 WAQI 空气质量指数，Cookie 自动记忆常用城市。
* **分类资讯**：涵盖 12 类主流 RSS 频道，集成正文清洗与 Pillow 图片等比缩放转码。
* **安全代理**：全站图片采用源站域名白名单防盗链代理，支持 Pillow 等比缩放与低功耗转码。
* **持久存储**：内置 SQLite (WAL 模式)，自动兼容本地与 Hugging Face 容器挂载卷，开箱即用。

## 部署

1. 在 [Hugging Face](https://huggingface.co/) 创建新的 Space，SDK 选择 **Docker**。
2. 将本项目代码推送到该 Space 关联的 Git 仓库。
3. Space 将自动构建并在 `7860` 端口上线运行。

## 配置

* **`WAQI_TOKEN`**：世界空气质量指数 API Token（可选，配置后天气详情展示 AQI 数据）。

## 协议

本项目基于 [MIT License](./LICENSE) 协议开源。

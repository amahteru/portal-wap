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

## 功能特性
- **经典门户导航**：原汁原味 XHTML Mobile 1.0 架构，适配全系列老旧功能机与现代浏览器
- **实时天气查询**：全国省市天气预报与空气质量索引
- **分类新闻资讯**：全自动 RSS 同步抓取与老机优化纯净正文阅读

## 环境变量配置

| 变量名 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `SECRET_KEY` | 生产推荐 | `portal_wap_default_secret_2026` | 用于新闻图片代理 URL 的 HMAC-SHA256 防篡改签名密钥。**生产环境务必配置，切勿使用默认密钥！** |
| `MONGO_URI` | 否 | 空 | MongoDB 异步连接串。未配置时系统自动优雅降级为全内存缓存模式。 |
| `SPACE_ID` | 否 | `default_space` | 集合隔离标识，用于区分多实例或 HuggingFace Space 部署。 |
| `WAQI_TOKEN` | 否 | 空 | WAQI 空气质量指数 API Token。未配置时天气模块将隐藏空气质量卡片。 |

### `SECRET_KEY` 安全配置方法

在生产部署前，必须生成高强度随机密钥：

```bash
# 方法 1：使用 OpenSSL
openssl rand -hex 32

# 方法 2：使用 Python secrets 模块
python -c "import secrets; print(secrets.token_hex(32))"
```

将生成的 64 位十六进制字符设置到环境变量 `SECRET_KEY` 中，防止老机图片代理接口被用于未授权请求或 SSRF 探测。

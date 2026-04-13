# CFDC – Playwright-stealth 抓取 & 翻译工具

通过 Playwright-stealth 全自动抓取 <https://developers.cloudflare.com> 下所有子路径的词条，
并翻译为中文。原词条保存在 `../i18n/en.json` 中，中文翻译保存在 `../i18n/zh-cn.json` 中。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 安装 Chromium 浏览器
playwright install chromium

# 3. 运行完整流水线
python main.py

# 或者分步运行
python main.py --urls-only         # 仅发现 URL
python main.py --extract-only      # 仅提取内容（需要先运行 --urls-only）
python main.py --translate-only    # 仅翻译（需要先运行 --extract-only）
python main.py --max-pages 10      # 仅处理前 10 个页面（调试用）
python main.py --bfs               # 同时使用 BFS 爬虫补充发现 URL
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `main.py` | 主入口 & 流程编排 |
| `crawler.py` | URL 发现（sitemap + BFS） |
| `extractor.py` | 页面内容提取 |
| `translator.py` | 英→中翻译（Google Translate 免费） |
| `config.py` | 全局配置（并发、超时、路径等） |
| `requirements.txt` | Python 依赖 |

## 输出

- `../i18n/en.json` – 英文原文词条
- `../i18n/zh-cn.json` – 中文翻译词条
- `urls.json` – URL 缓存（中间文件）
- `entries_cache.json` – 抓取进度缓存（支持断点续爬）

## 详细规划

参见 [../docs/plan.md](../docs/plan.md)。
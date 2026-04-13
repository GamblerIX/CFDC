# CFDC 数据抓取与翻译计划

## 目标

使用 Playwright-stealth 全自动抓取 `https://developers.cloudflare.com` 下所有子路径的词条（文本内容），将英文原文保存在 `i18n/en.json`，中文翻译保存在 `i18n/zh-cn.json`。

## 架构概览

```
pythonplaywrightstealth/
├── requirements.txt      # 依赖列表
├── main.py               # 主入口 & 流程编排
├── crawler.py            # URL 发现 + 页面内容抓取
├── extractor.py          # 从页面 HTML 中提取可翻译词条
├── translator.py         # 英 → 中翻译（deep-translator / Google Translate 免费）
├── config.py             # 全局配置（并发数、超时、输出路径等）
└── Readme.md             # 已有说明
```

## 详细步骤

### Phase 1 — URL 发现

1. **Sitemap 优先**：先请求 `https://developers.cloudflare.com/sitemap.xml`（及嵌套 sitemap），解析出全量 URL 列表。  
2. **BFS 补充**：如果 sitemap 不完整，使用 Playwright-stealth 从首页出发 BFS 遍历，提取所有同域 `<a href>` 链接。  
3. **去重 & 过滤**：排除非文档页面（API JSON、图片、PDF 等），保留 HTML 文档页。  
4. 输出中间文件 `urls.json` 供调试和断点续爬。

### Phase 2 — 页面内容抓取

1. 使用 `playwright-stealth` 启动 Chromium，逐页访问 URL 列表。  
2. 等待页面完全渲染（`networkidle`）。  
3. 提取关键区域的文本：
   - 导航栏 / 侧边栏菜单项  
   - 页面标题 (`h1` ~ `h6`)  
   - 段落文本 (`p`, `li`, `td`, `th`, `blockquote`)  
   - 按钮 / 标签 (`button`, `a`, `span` 中的 UI 文案)  
   - 代码注释（可选）  
4. 以 **路径 + CSS 选择器** 作为 key，保证词条可定位。
5. 支持断点续爬：已完成的 URL 跳过。

### Phase 3 — 翻译

1. 使用 `deep-translator`（Google Translate 免费接口）批量翻译。  
2. 自动限速，避免触发 API 限制。  
3. 对专有名词（Cloudflare、Workers、Pages、R2、D1 等）保留英文不翻译。  
4. 输出 `i18n/zh-cn.json`，key 与 `i18n/en.json` 一一对应。

### Phase 4 — 输出 & 验证

1. 生成 `i18n/en.json` 和 `i18n/zh-cn.json`。  
2. 校验 JSON 格式正确、key 一致。  
3. 抽样对比翻译质量。

## 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 浏览器自动化 | Playwright + playwright-stealth | 反爬绕过、JS 渲染支持 |
| URL 发现 | sitemap.xml + BFS | 覆盖全面 |
| 翻译 | deep-translator (Google) | 免费、无需 API key |
| 数据格式 | 扁平 JSON（path-based key） | UserScript 易于查找替换 |

## i18n JSON 格式设计

```json
// en.json 示例
{
  "/workers/": {
    "h1": "Cloudflare Workers",
    "nav": ["Overview", "Get started", "Configuration", ...],
    "p_0": "Build serverless applications...",
    ...
  },
  "/r2/": { ... }
}

// zh-cn.json 示例（key 完全相同）
{
  "/workers/": {
    "h1": "Cloudflare Workers",
    "nav": ["概述", "快速开始", "配置", ...],
    "p_0": "构建无服务器应用...",
    ...
  }
}
```

## 运行方式

```bash
cd pythonplaywrightstealth
pip install -r requirements.txt
playwright install chromium
python main.py
```

## 注意事项

- Cloudflare 开发者文档页面众多（数千页），完整抓取预计需要数小时。
- 可通过 `config.py` 中的 `MAX_PAGES` 限制抓取数量，便于调试。
- 翻译速度受 Google Translate 免费接口限制，自动限速处理。
- 专有名词保持英文原文（Cloudflare、Workers、KV、R2、D1、Pages、Wrangler 等）。

## 两种数据源

### 方式一：Playwright-stealth 直接抓取（推荐，需要网络访问）
使用 `main.py`，通过 Playwright-stealth 打开浏览器直接访问 developers.cloudflare.com，
从渲染后的页面中提取文本。这种方式可以获取最完整、最准确的内容。

```bash
python main.py --bfs --max-pages 100
```

### 方式二：GitHub 源码抓取（备用方案）
使用 `github_scraper.py`，从 cloudflare/cloudflare-docs 仓库的 MDX 源文件中提取文本。
此方式不需要浏览器，适合在网络受限环境或 CI/CD 中使用。

```bash
python build_file_list.py          # 发现所有 MDX 文件
python github_scraper.py           # 提取内容并翻译
python github_scraper.py --online  # 使用 Google Translate 在线翻译
```

## 翻译方式

### 离线翻译（默认）
使用内置的技术术语词典进行关键词替换。速度快，但翻译质量有限。
适合在网络受限环境中使用，生成的翻译可作为人工翻译的基础。

### 在线翻译（推荐）
使用 Google Translate 免费接口进行完整句子翻译。
需要能访问 translate.google.com。

```bash
python github_scraper.py --online
```

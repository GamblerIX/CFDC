# CFDC – Cloudflare Developer Docs Crawler & Translator

全自动抓取 <https://developers.cloudflare.com> 下所有文档页面的可翻译文本，并生成中文翻译。英文原文保存在 `../i18n/en.json`，中文翻译保存在 `../i18n/zh-cn.json`。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 发现所有文档文件（通过 GitHub API，~6000+ 个 MDX 文件）
python build_file_list.py

# 3. 提取内容并翻译（离线模式）
python github_scraper.py

# 4. 验证输出
python validate.py
```

## 两种数据源

### 方式一：GitHub 源码提取（推荐，主要链路）

从 `cloudflare/cloudflare-docs` 仓库的 MDX 源文件中提取文本。覆盖率最高（100%），速度快，无需浏览器。

```bash
python build_file_list.py          # 发现所有 MDX 文件（通过 GitHub API 递归树）
python github_scraper.py           # 提取内容并离线翻译
python github_scraper.py --online  # 使用 Google Translate 在线翻译（质量更好）
```

### 方式二：Playwright-stealth 直接抓取（补充校验）

使用 Playwright-stealth 打开浏览器直接访问 developers.cloudflare.com，从渲染后的页面中提取文本。适合用于抽样复核或补漏。

```bash
playwright install chromium
python main.py --bfs --max-pages 100
```

## 分阶段运行

```bash
# 仅发现文件
python build_file_list.py

# 仅提取内容（不翻译）
python github_scraper.py --skip-translate

# 指定特定 section
python github_scraper.py --sections workers pages r2

# 限制页面数量（调试用）
python github_scraper.py --max-pages 50

# 忽略缓存，重新下载
python github_scraper.py --fresh

# 自定义并发数
python github_scraper.py --concurrency 16
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `build_file_list.py` | 通过 GitHub API 递归树发现所有 MDX 文件 |
| `github_scraper.py` | 下载 MDX 文件、提取文本、调用翻译 |
| `translator.py` | 翻译引擎：在线(Google) → 离线短语匹配 → 原文保留 |
| `validate.py` | 输出验证：key 对齐、覆盖率、质量检查 |
| `main.py` | Playwright 浏览器抓取入口（补充链路） |
| `crawler.py` | URL 发现（sitemap + BFS） |
| `extractor.py` | 浏览器页面内容提取 |
| `config.py` | 全局配置（并发、超时、路径、术语保护列表） |
| `file_list.json` | 文件发现缓存（MDX 文件列表，按 section 分组） |

## 输出

- `../i18n/en.json` – 英文原文词条（~6000+ 页面）
- `../i18n/zh-cn.json` – 中文翻译词条（key 与 en.json 完全一致）
- `file_list.json` – 文件发现缓存
- `cache/` – 运行时缓存目录（MDX 文件、提取进度、翻译缓存）

## 翻译策略

翻译按优先级分三层：

1. **在线翻译（`--online`）**：通过 Google Translate 翻译完整句子，术语自动保护。质量最好，需要网络。
2. **离线短语匹配**：匹配 500+ 常见标签、短语和术语的中文翻译。用于导航、标题等短文本。
3. **原文保留**：无法通过离线匹配完整翻译的句子，保留英文原文（前缀 `[EN]`），避免产生中英混杂的低质量翻译。

### 术语保护

以下类型的内容在翻译时自动保护（不翻译）：
- Cloudflare 产品名（Workers、Pages、R2、D1、KV 等 120+ 个）
- URL、文件路径、版本号
- 环境变量名（`UPPER_CASE`）
- CLI 参数（`--flag-name`）
- 行内代码

## 验证

```bash
python validate.py          # 运行完整验证
python validate.py --verbose  # 显示详细问题列表
```

验证内容：
1. **Key 对齐** – en.json 与 zh-cn.json 的所有 key 完全一致
2. **空值检测** – 检查非空英文对应空中文的情况
3. **覆盖率** – file_list.json 中的页面 vs en.json 中的页面
4. **翻译质量** – 英文残留率、术语保护违规、重复值、长文本未翻译

## 断点续跑

所有步骤都支持断点续跑：
- `build_file_list.py` 会覆写 `file_list.json`
- `github_scraper.py` 通过 `cache/` 目录缓存已下载的 MDX 文件和已提取的条目
- 翻译器通过 `cache/translation_cache.json` 缓存已翻译的文本
- 使用 `--fresh` 参数可忽略缓存重新开始

## 数据统计

最近一次运行结果：
- 发现 MDX 文件：**6,156** 个（99 个 section）
- 成功下载：**6,156** 个（100%）
- 成功提取：**6,156** 个（100%）
- 总文本条目：**~151,000+** 条
- 离线翻译覆盖：~61%（短标签和已知短语）
- 需在线翻译：~39%（标记为 `[EN]` 前缀）

## 详细规划

参见 [../docs/plan.md](../docs/plan.md)。
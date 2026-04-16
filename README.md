# CFDC（Cloudflare Developers 文档中文化）

CFDC 用于抓取并翻译 Cloudflare Developers 文档内容，产出标准 i18n 词条文件：

- `i18n/en.json`：英文原文词条
- `i18n/zh-cn.json`：中文翻译词条
- `i18n/userscript-en.json`：用户脚本独立英文词条
- `i18n/userscript-zh-cn.json`：用户脚本独立中文词条

本仓库已移除运行缓存机制，任务默认按“全量执行、直接输出结果”方式运行。

## 目录说明

- `pythonplaywrightstealth/build_file_list.py`：从 `cloudflare/cloudflare-docs` 发现 MDX 文件
- `pythonplaywrightstealth/github_scraper.py`：下载并抽取 MDX 文本，写入 i18n
- `pythonplaywrightstealth/main.py`：基于浏览器抓取链路的总入口
- `pythonplaywrightstealth/translate_remaining.py`：并发翻译 `[EN]` 前缀的剩余条目
- `pythonplaywrightstealth/validate.py`：校验 key 对齐、覆盖率和翻译质量
- `.github/workflows/translate.yml`：手动触发的自动翻译工作流
- `cfdc.user.js`：浏览器用户脚本（只读取独立 userscript 词条，不依赖自动翻译产物）

## 快速开始

```bash
cd pythonplaywrightstealth
pip install -r requirements.txt
```

### 方案一：基于 GitHub 源文件（推荐）

```bash
python build_file_list.py
python github_scraper.py
python validate.py
```

### 方案二：基于浏览器抓取（补充）

```bash
playwright install chromium
python main.py --bfs --max-pages 100
```

## 常用命令

```bash
# 仅统计仍带 [EN] 前缀的条目
python translate_remaining.py --dry-run

# 并发翻译剩余条目
python translate_remaining.py --workers 8 --max-runtime-minutes 180

# 校验翻译结果
python validate.py --verbose
```

## 输出文件

- `i18n/en.json`
- `i18n/zh-cn.json`
- `pythonplaywrightstealth/file_list.json`
- `pythonplaywrightstealth/urls.json`
- `pythonplaywrightstealth/entries.json`
- `pythonplaywrightstealth/validation_report.json`

## 说明

- 术语保护会尽量避免把 Cloudflare 产品名、命令参数、URL、代码片段误翻。
- 若在线翻译失败，相关条目会保留原文（通常带 `[EN] ` 前缀），可后续补翻。

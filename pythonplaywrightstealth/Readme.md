# pythonplaywrightstealth 子模块说明

该目录包含 CFDC 的抓取、提取、翻译与校验脚本。

## 安装依赖

```bash
pip install -r requirements.txt
```

## 典型流程

```bash
# 1) 发现 Cloudflare 文档 MDX 文件
python build_file_list.py

# 2) 执行抓取 + 提取 + 翻译
python github_scraper.py

# 3) 校验输出质量
python validate.py
```

## 仅翻译剩余英文条目

```bash
# 查看数量
python translate_remaining.py --dry-run

# 开始翻译
python translate_remaining.py --workers 8 --max-runtime-minutes 180
```

## 仅浏览器抓取链路

```bash
playwright install chromium
python main.py --bfs --max-pages 100
```

## 结果文件

- `../i18n/en.json`
- `../i18n/zh-cn.json`
- `file_list.json`
- `urls.json`
- `entries.json`
- `validation_report.json`

## 设计原则

- 以可复现的全量执行为主，不依赖运行缓存。
- 尽量保护 Cloudflare 专有术语、命令参数和代码片段。
- 优先保证 key 对齐与数据一致性，再提升翻译覆盖率。

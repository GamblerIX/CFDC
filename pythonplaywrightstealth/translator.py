"""
translator.py – Translate extracted English entries to Chinese.

Translation backends in priority order:
1. **Online** – Google Translate via deep-translator (best quality, needs network)
2. **Offline phrase-based** – exact / substring matching from PHRASE_DICT
3. **Passthrough** – keeps the English original rather than producing mixed garbage

Core principle: never mix Chinese and English words in the same sentence.
If a sentence cannot be fully translated offline, keep the English original
(optionally prefixed with "[EN] ") instead of doing word-by-word replacement.
"""

import hashlib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import config

logger = logging.getLogger(__name__)

# ─── Phrase dictionary ──────────────────────────────────────────────────────
# Used for exact-match and substring-match of short labels / known phrases.
# Intentionally does NOT include a word-level dictionary – word-by-word
# replacement is the root cause of gibberish mixed-language output.

PHRASE_DICT: Dict[str, str] = {
    # ── Navigation & UI labels ───────────────────────────────────────────
    "Get started": "快速开始",
    "Getting started": "快速开始",
    "Overview": "概述",
    "Introduction": "简介",
    "Configuration": "配置",
    "Reference": "参考",
    "Examples": "示例",
    "Tutorials": "教程",
    "Guides": "指南",
    "Guide": "指南",
    "Pricing": "定价",
    "Platform": "平台",
    "Limits": "限制",
    "Troubleshooting": "故障排除",
    "FAQ": "常见问题",
    "Changelog": "更新日志",
    "Release notes": "发行说明",
    "Migration guide": "迁移指南",
    "Quickstart": "快速开始",
    "Quick start": "快速开始",
    "Prerequisites": "前提条件",
    "Requirements": "要求",
    "Setup": "设置",
    "Set up": "设置",
    "Install": "安装",
    "Installation": "安装",
    "Deploy": "部署",
    "Deployment": "部署",
    "Build": "构建",
    "Test": "测试",
    "Testing": "测试",
    "Debug": "调试",
    "Debugging": "调试",
    "Monitor": "监控",
    "Monitoring": "监控",
    "Observe": "观察",
    "Observability": "可观测性",
    "Security": "安全",
    "Performance": "性能",
    "Optimization": "优化",
    "Best practices": "最佳实践",
    "Learn more": "了解更多",
    "Read more": "阅读更多",
    "See also": "另请参阅",
    "Related": "相关",
    "Note": "注意",
    "Warning": "警告",
    "Caution": "注意",
    "Important": "重要",
    "Tip": "提示",
    "Example": "示例",
    "Deprecated": "已弃用",
    "Beta": "测试版",
    "Alpha": "内测版",
    "Experimental": "实验性",
    "Coming soon": "即将推出",
    "New": "新功能",
    "Updated": "已更新",
    "Features": "特性",
    "Feature": "特性",
    "Benefits": "优势",
    "Availability": "可用性",
    "Compatibility": "兼容性",
    "Supported": "支持的",
    "Unsupported": "不支持的",
    "Authentication": "身份验证",
    "Authorization": "授权",
    "Permissions": "权限",
    "Roles": "角色",
    "Settings": "设置",
    "Account": "账户",
    "Dashboard": "控制面板",
    "Logs": "日志",
    "Metrics": "指标",
    "Analytics": "分析",
    "Reports": "报告",
    "Notifications": "通知",
    "Alerts": "告警",
    "Events": "事件",
    "Webhooks": "Webhook",
    "Integrations": "集成",
    "Plugins": "插件",
    "Extensions": "扩展",
    "Add-ons": "附加组件",
    "Modules": "模块",
    "Packages": "包",
    "Dependencies": "依赖",
    "Libraries": "库",
    "Frameworks": "框架",
    "Tools": "工具",
    "Resources": "资源",
    "Documentation": "文档",
    "API reference": "API 参考",
    "Endpoints": "端点",
    "Methods": "方法",
    "Parameters": "参数",
    "Response": "响应",
    "Request": "请求",
    "Headers": "头部",
    "Body": "正文",
    "Status codes": "状态码",
    "Errors": "错误",
    "Error handling": "错误处理",
    "Rate limiting": "速率限制",
    "Pagination": "分页",
    "Filtering": "过滤",
    "Sorting": "排序",
    "Search": "搜索",
    "Create": "创建",
    "Read": "读取",
    "Update": "更新",
    "Delete": "删除",
    "List": "列表",
    "Get": "获取",
    "Manage": "管理",
    "Configure": "配置",
    "Enable": "启用",
    "Disable": "禁用",
    "Connect": "连接",
    "Disconnect": "断开连接",
    "Upload": "上传",
    "Download": "下载",
    "Import": "导入",
    "Export": "导出",
    "Publish": "发布",
    "Preview": "预览",
    "Save": "保存",
    "Cancel": "取消",
    "Confirm": "确认",
    "Submit": "提交",
    "Reset": "重置",
    "Retry": "重试",
    "Back": "返回",
    "Next": "下一步",
    "Previous": "上一步",
    "Close": "关闭",
    "Open": "打开",
    "Edit": "编辑",
    "Copy": "复制",
    "Paste": "粘贴",
    "Select": "选择",
    "Remove": "移除",
    "Add": "添加",
    "View": "查看",
    "Show": "显示",
    "Hide": "隐藏",
    "Expand": "展开",
    "Collapse": "折叠",
    "Refresh": "刷新",
    "Loading": "加载中",
    "Saving": "保存中",

    # ── Cloudflare-specific technical terms ───────────────────────────────
    "serverless": "无服务器",
    "edge computing": "边缘计算",
    "edge network": "边缘网络",
    "global network": "全球网络",
    "data center": "数据中心",
    "data centers": "数据中心",
    "point of presence": "接入点",
    "content delivery network": "内容分发网络",
    "domain name system": "域名系统",
    "reverse proxy": "反向代理",
    "load balancer": "负载均衡器",
    "firewall": "防火墙",
    "web application firewall": "Web 应用防火墙",
    "distributed denial of service": "分布式拒绝服务",
    "bot management": "机器人管理",
    "rate limiting": "速率限制",
    "caching": "缓存",
    "cache purge": "缓存清除",
    "cache invalidation": "缓存失效",
    "origin server": "源服务器",
    "upstream": "上游",
    "downstream": "下游",
    "worker": "Worker",
    "binding": "绑定",
    "bindings": "绑定",
    "environment variable": "环境变量",
    "environment variables": "环境变量",
    "secret": "密钥",
    "secrets": "密钥",
    "namespace": "命名空间",
    "bucket": "存储桶",
    "object storage": "对象存储",
    "key-value store": "键值存储",
    "database": "数据库",
    "query": "查询",
    "migration": "迁移",
    "schema": "模式",
    "table": "表",
    "index": "索引",
    "transaction": "事务",
    "durability": "持久性",
    "consistency": "一致性",
    "replication": "复制",
    "backup": "备份",
    "restore": "恢复",
    "snapshot": "快照",
    "routing": "路由",
    "route": "路由",
    "routes": "路由",
    "handler": "处理程序",
    "middleware": "中间件",
    "trigger": "触发器",
    "cron trigger": "定时触发器",
    "scheduled": "定时",
    "event": "事件",
    "queue": "队列",
    "message": "消息",
    "producer": "生产者",
    "consumer": "消费者",
    "subscriber": "订阅者",
    "publisher": "发布者",
    "stream": "流",
    "pipeline": "管道",
    "workflow": "工作流",
    "step": "步骤",
    "task": "任务",
    "job": "作业",
    "function": "函数",
    "runtime": "运行时",
    "execution": "执行",
    "invocation": "调用",
    "concurrency": "并发",
    "timeout": "超时",
    "retry": "重试",
    "retries": "重试",
    "fallback": "回退",
    "circuit breaker": "断路器",
    "health check": "健康检查",
    "health checks": "健康检查",
    "uptime": "正常运行时间",
    "downtime": "停机时间",
    "latency": "延迟",
    "throughput": "吞吐量",
    "bandwidth": "带宽",
    "request": "请求",
    "response": "响应",
    "header": "头部",
    "cookie": "Cookie",
    "session": "会话",
    "token": "令牌",
    "certificate": "证书",
    "encryption": "加密",
    "decryption": "解密",
    "handshake": "握手",
    "protocol": "协议",
    "hostname": "主机名",
    "subdomain": "子域名",
    "domain": "域名",
    "zone": "区域",
    "record": "记录",
    "nameserver": "名称服务器",
    "resolver": "解析器",
    "proxy": "代理",
    "connector": "连接器",
    "endpoint": "端点",
    "origin": "源",
    "custom domain": "自定义域名",
    "custom domains": "自定义域名",
    "wildcard": "通配符",
    "redirect": "重定向",
    "rewrite": "重写",
    "transform": "转换",
    "rule": "规则",
    "rules": "规则",
    "expression": "表达式",
    "filter": "过滤器",
    "action": "操作",
    "condition": "条件",
    "variable": "变量",
    "field": "字段",
    "value": "值",
    "key": "键",
    "pair": "对",
    "type": "类型",
    "string": "字符串",
    "number": "数字",
    "boolean": "布尔值",
    "array": "数组",
    "object": "对象",
    "null": "空值",
    "default": "默认",
    "optional": "可选",
    "required": "必需",
    "enabled": "已启用",
    "disabled": "已禁用",
    "active": "活跃",
    "inactive": "不活跃",
    "pending": "待处理",
    "running": "运行中",
    "stopped": "已停止",
    "failed": "已失败",
    "success": "成功",
    "error": "错误",
    "warning": "警告",
    "info": "信息",

    # ── Sentences / multi-word phrases common in Cloudflare docs ──────────
    "Related products": "相关产品",
    "What you will learn": "您将学到什么",
    "Before you begin": "开始之前",
    "Next steps": "后续步骤",
    "Additional resources": "其他资源",
    "How it works": "工作原理",
    "Use cases": "使用场景",
    "Known issues": "已知问题",
    "Known limitations": "已知限制",
    "Community": "社区",
    "Feedback": "反馈",
    "Support": "支持",
    "Contact us": "联系我们",
    "Sign up": "注册",
    "Log in": "登录",
    "Sign in": "登录",
    "Subscribe": "订阅",
    "Free plan": "免费计划",
    "Pro plan": "专业计划",
    "Business plan": "商业计划",
    "Enterprise plan": "企业计划",
    "Paid plans": "付费计划",
    "All plans": "所有计划",
    "Workers plan": "Workers 计划",
    "Select a plan": "选择计划",
    "Compare plans": "比较计划",
    "View plans": "查看计划",
    "Explore plans": "探索计划",
    "In this article": "本文内容",
    "On this page": "本页内容",
    "Table of contents": "目录",
    "Was this helpful?": "这对您有帮助吗？",
    "Last updated": "最后更新",
    "Edit this page": "编辑此页",
    "Report an issue": "报告问题",
    "View source": "查看源码",
    "External link": "外部链接",
    "Internal link": "内部链接",
    "Permalink": "永久链接",
    "Share": "分享",
    "Print": "打印",
    "Copied": "已复制",
    "Copy to clipboard": "复制到剪贴板",
    "Click to copy": "点击复制",
    "Toggle navigation": "切换导航",
    "Skip to content": "跳到内容",
    "Scroll to top": "回到顶部",
    "Show more": "显示更多",
    "Show less": "收起",
    "Load more": "加载更多",
    "See all": "查看全部",
    "View all": "查看全部",
    "Clear all": "全部清除",
    "Select all": "全选",
    "No results found": "未找到结果",
    "No results": "无结果",
    "Try again": "重试",
    "Something went wrong": "出错了",
    "Page not found": "页面未找到",
    "Access denied": "拒绝访问",
    "Permission denied": "权限被拒绝",
    "Not available": "不可用",
    "Coming soon": "即将推出",
    "Under construction": "建设中",
    "Work in progress": "进行中",
    "Stay tuned": "敬请期待",
    "Thank you": "谢谢",
    "Welcome": "欢迎",
    "Hello": "你好",
    "Good morning": "早上好",
    "Home": "首页",
    "Menu": "菜单",
    "Sidebar": "侧边栏",
    "Footer": "页脚",
    "Header": "页眉",
    "Navigation": "导航",
    "Breadcrumb": "面包屑导航",
    "Tab": "选项卡",
    "Tabs": "选项卡",
    "Panel": "面板",
    "Modal": "模态框",
    "Dialog": "对话框",
    "Tooltip": "工具提示",
    "Dropdown": "下拉菜单",
    "Toggle": "切换",
    "Switch": "开关",
    "Checkbox": "复选框",
    "Radio": "单选",
    "Input": "输入",
    "Output": "输出",
    "Form": "表单",
    "Button": "按钮",
    "Link": "链接",
    "Icon": "图标",
    "Badge": "徽章",
    "Banner": "横幅",
    "Card": "卡片",
    "Snippet": "代码片段",
    "Code block": "代码块",
    "Inline code": "行内代码",
    "Syntax highlighting": "语法高亮",
    "Dark mode": "深色模式",
    "Light mode": "浅色模式",
    "Theme": "主题",
    "Language": "语言",
    "Version": "版本",
    "Versions": "版本",

    # ── Common Cloudflare doc headings and phrases ────────────────────────
    "Workers documentation": "Workers 文档",
    "Pages documentation": "Pages 文档",
    "R2 documentation": "R2 文档",
    "D1 documentation": "D1 文档",
    "KV documentation": "KV 文档",
    "Durable Objects documentation": "Durable Objects 文档",
    "Hyperdrive documentation": "Hyperdrive 文档",
    "Queues documentation": "Queues 文档",
    "API Shield": "API Shield",
    "Bot Management": "Bot Management",
    "Page Shield": "Page Shield",
    "Cloudflare Radar": "Cloudflare Radar",
    "Speed": "速度",
    "Caching": "缓存",
    "Rules": "规则",
    "Transform Rules": "转换规则",
    "Page Rules": "页面规则",
    "Firewall rules": "防火墙规则",
    "WAF rules": "WAF 规则",
    "Rate limiting rules": "速率限制规则",
    "Custom rules": "自定义规则",
    "Managed rules": "托管规则",
    "Configuration rules": "配置规则",
    "Origin rules": "源规则",
    "Redirect rules": "重定向规则",
    "Bulk redirects": "批量重定向",
    "DNS records": "DNS 记录",
    "SSL certificates": "SSL 证书",
    "Edge certificates": "边缘证书",
    "Origin certificates": "源证书",
    "Client certificates": "客户端证书",
    "Custom certificates": "自定义证书",
    "Total TLS": "Total TLS",
    "Universal SSL": "Universal SSL",
    "Advanced certificates": "高级证书",
    "Access policies": "Access 策略",
    "Access groups": "Access 组",
    "Access applications": "Access 应用",
    "Service tokens": "服务令牌",
    "API tokens": "API 令牌",
    "API keys": "API 密钥",
    "Audit logs": "审计日志",
    "Account members": "账户成员",
    "Notifications and alerts": "通知和告警",
    "Wrangler commands": "Wrangler 命令",
    "Smart placement": "智能放置",
    "Tail Workers": "Tail Workers",
    "Cron Triggers": "定时触发器",
    "Custom Domains": "自定义域名",
    "Environment variables and secrets": "环境变量和密钥",
    "Source code": "源代码",
    "Sample code": "示例代码",
    "Code example": "代码示例",
    "Code examples": "代码示例",
    "Full example": "完整示例",
    "Starter template": "入门模板",
    "Starter templates": "入门模板",
    "Template": "模板",
    "Templates": "模板",
    "Playground": "在线演练场",
    "Quick edit": "快速编辑",
    "Local development": "本地开发",
    "Remote development": "远程开发",
    "Continuous integration": "持续集成",
    "Continuous deployment": "持续部署",
    "Git integration": "Git 集成",
    "Branch deployments": "分支部署",
    "Preview deployments": "预览部署",
    "Production deployments": "生产部署",
    "Build configuration": "构建配置",
    "Build commands": "构建命令",
    "Build output": "构建输出",
    "Framework guide": "框架指南",
    "Framework guides": "框架指南",
    "Functions": "函数",
    "Bindings": "绑定",
    "Static assets": "静态资源",
    "Dynamic content": "动态内容",
    "Server-side rendering": "服务端渲染",
    "Single-page application": "单页应用",
    "Static site": "静态站点",
    "Full-stack": "全栈",
    "Jamstack": "Jamstack",
}

# Build a case-insensitive lookup for PHRASE_DICT (lowered key → translation)
_PHRASE_LOWER: Dict[str, str] = {k.lower(): v for k, v in PHRASE_DICT.items()}

# ─── Term protection ────────────────────────────────────────────────────────
# Patterns that should never be translated: product names from config,
# URLs, file paths, version numbers, env-var names, inline code, etc.

# Build regex for config.NO_TRANSLATE_TERMS (longest first for greedy match)
_NO_TRANSLATE_SORTED = sorted(
    config.NO_TRANSLATE_TERMS, key=len, reverse=True
)
_TERMS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _NO_TRANSLATE_SORTED) + r")\b",
    re.IGNORECASE,
)

# Additional patterns to protect from translation
_EXTRA_PROTECT_PATTERNS: List[re.Pattern] = [
    re.compile(r"https?://\S+"),                          # URLs
    re.compile(r"(?<!\w)/[\w./_-]+"),                     # file paths like /etc/resolv.conf
    re.compile(r"\b\w+\.\w+\.\w[\w.]*\b"),               # dotted identifiers: wrangler.toml, crypto.subtle
    re.compile(r"\bv?\d+\.\d+(?:\.\d+)(?:[-+]\S+)?\b"),  # version numbers: v1.2.3, 2.0.0-beta
    re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b"),    # ENV_VAR_NAMES
    re.compile(r"`[^`]+`"),                                # inline code
    re.compile(r"\{[^}]+\}"),                              # template expressions {variable}
    re.compile(r"--[\w-]+"),                               # CLI flags --flag-name
]

def _protect_terms(text: str) -> Tuple[str, List[str]]:
    """Replace protected terms / patterns with numbered placeholders."""
    protected: List[str] = []

    def _replace(m: re.Match) -> str:
        idx = len(protected)
        protected.append(m.group(0))
        return f"\u27e6{idx}\u27e7"

    # 1. Config no-translate terms
    text = _TERMS_RE.sub(_replace, text)
    # 2. Extra patterns (URLs, paths, versions, env vars, inline code, …)
    for pat in _EXTRA_PROTECT_PATTERNS:
        text = pat.sub(_replace, text)
    return text, protected


def _restore_terms(text: str, protected: List[str]) -> str:
    """Restore placeholders back to original terms."""
    for idx, term in enumerate(protected):
        text = text.replace(f"\u27e6{idx}\u27e7", term)
    return text


def _has_placeholder_artifacts(text: str) -> bool:
    """Check whether any placeholder markers leaked into the output."""
    return bool(re.search(r"\u27e6\d+\u27e7", text))


# ─── Translation cache ──────────────────────────────────────────────────────

_translation_cache: Dict[str, str] = {}


def _cache_key(text: str) -> str:
    """Return a cache key: short texts verbatim, long texts as sha256."""
    if len(text) <= 200:
        return text
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _load_cache() -> None:
    """缓存机制已移除：每次运行从空状态开始。"""
    global _translation_cache
    _translation_cache = {}


def _save_cache() -> None:
    """缓存机制已移除：不再落盘。"""
    return


def _get_cached(text: str) -> Optional[str]:
    return _translation_cache.get(_cache_key(text))


def _set_cached(text: str, translation: str) -> None:
    _translation_cache[_cache_key(text)] = translation


# ─── Text classification helpers ────────────────────────────────────────────

def _word_count(text: str) -> int:
    return len(text.split())


def _is_technical(text: str) -> bool:
    """Heuristic: text is 'technical' if >40 % of tokens are protected terms."""
    protected_text, protected = _protect_terms(text)
    if not protected:
        return False
    # Rough ratio: fraction of characters consumed by placeholders
    original_len = len(text.strip())
    placeholder_chars = sum(len(t) for t in protected)
    return (placeholder_chars / max(original_len, 1)) > 0.40


# ─── Online translation (Google Translate) ──────────────────────────────────

_google_translator = None  # lazy singleton


def _get_google_translator():
    global _google_translator
    if _google_translator is None:
        from deep_translator import GoogleTranslator
        _google_translator = GoogleTranslator(source="en", target="zh-CN")
    return _google_translator


def _online_translate_single(text: str) -> Optional[str]:
    """Translate *one* string via Google Translate. Returns None on failure."""
    try:
        translator = _get_google_translator()
        result = translator.translate(text)
        if result and isinstance(result, str) and result.strip():
            return result
        return None
    except Exception as exc:
        logger.debug("在线翻译失败：%s", exc)
        return None


def _online_translate_batch(texts: List[str]) -> List[Optional[str]]:
    """
    Translate a batch via Google Translate.
    Falls back to one-by-one if the batch API isn't supported.
    """
    try:
        translator = _get_google_translator()
        results = translator.translate_batch(texts)
        return [
            r if (isinstance(r, str) and r.strip()) else None
            for r in results
        ]
    except Exception:
        # Fallback: one at a time
        out: List[Optional[str]] = []
        for t in texts:
            out.append(_online_translate_single(t))
            time.sleep(config.TRANSLATE_DELAY)
        return out


# ─── Core single-text translation ──────────────────────────────────────────

def _translate_single(text: str, use_online: bool = False) -> str:
    """
    Translate a single English string to Chinese.

    Strategy:
      1. Check translation cache.
      2. Try exact phrase-dict match (any length).
      3. If use_online, try Google Translate with term protection.
      4. Offline: short labels (≤5 words) → phrase match; medium (≤20) → phrase
         substring match; long → passthrough.
      5. Never produce mixed Chinese/English gibberish.
    """
    if not text or not text.strip():
        return text

    stripped = text.strip()

    # Very short non-word content (punctuation, numbers, single chars)
    if len(stripped) <= 2:
        return text

    # ── Cache hit ────────────────────────────────────────────────────────
    cached = _get_cached(stripped)
    if cached is not None:
        return cached

    # ── Exact phrase-dict match (case-insensitive) ───────────────────────
    lower = stripped.lower()
    if lower in _PHRASE_LOWER:
        result = _PHRASE_LOWER[lower]
        _set_cached(stripped, result)
        return result

    # ── Online translation with term protection ─────────────────────────
    if use_online:
        result = _translate_online_protected(stripped)
        if result is not None:
            _set_cached(stripped, result)
            return result

    # ── Offline phrase-based translation ─────────────────────────────────
    return _translate_offline(stripped)


def _translate_online_protected(text: str) -> Optional[str]:
    """
    Protect terms → translate via Google → restore terms.
    Returns None if online fails.
    """
    protected_text, protected = _protect_terms(text)
    translated = _online_translate_single(protected_text)
    if translated is None:
        return None
    restored = _restore_terms(translated, protected)
    # Quality check
    if _has_placeholder_artifacts(restored):
        logger.debug("在线翻译后占位符残留，改为不保护重试")
        # Try a plain translation as last resort
        plain = _online_translate_single(text)
        if plain and not _has_placeholder_artifacts(plain):
            return plain
        return None
    return restored


def _translate_offline(text: str) -> str:
    """
    Offline translation: phrase matching only, never word-by-word.

    - Short (≤5 words): exact phrase-dict match or passthrough.
    - Medium (≤20 words): try to match known sub-phrases; if the entire text
      can be covered, use it; otherwise passthrough.
    - Long (>20 words): passthrough with [EN] prefix.
    """
    words = _word_count(text)

    # Short labels: try exact match (already tried above in _translate_single)
    # but also try after stripping trailing punctuation / minor differences.
    if words <= 5:
        result = _try_phrase_match(text)
        if result is not None:
            _set_cached(text, result)
            return result
        # Short text with no match – if it's mostly a protected term, keep it
        if _is_technical(text):
            _set_cached(text, text)
            return text
        return _passthrough(text, short=True)

    # Medium text: try full substring coverage
    if words <= 20:
        result = _try_full_phrase_coverage(text)
        if result is not None:
            _set_cached(text, result)
            return result
        if _is_technical(text):
            _set_cached(text, text)
            return text
        return _passthrough(text, short=False)

    # Long text: never attempt offline, keep English
    if _is_technical(text):
        _set_cached(text, text)
        return text
    return _passthrough(text, short=False)


def _try_phrase_match(text: str) -> Optional[str]:
    """
    Try matching text against PHRASE_DICT with minor normalization.
    Returns translation or None.
    """
    stripped = text.strip()
    lower = stripped.lower()
    # exact
    if lower in _PHRASE_LOWER:
        return _PHRASE_LOWER[lower]
    # strip trailing colon / punctuation
    cleaned = re.sub(r"[:.!?]+$", "", stripped).strip()
    if cleaned.lower() in _PHRASE_LOWER:
        return _PHRASE_LOWER[cleaned.lower()]
    return None


def _try_full_phrase_coverage(text: str) -> Optional[str]:
    """
    Try to fully translate text by matching known phrases as substrings.
    Only returns a result if the ENTIRE text is covered (no leftover English
    words mixed with Chinese). Protected terms are allowed as-is.
    """
    protected_text, protected = _protect_terms(text)

    # Try to replace all known phrases in the protected text
    result = protected_text
    sorted_phrases = sorted(PHRASE_DICT.keys(), key=len, reverse=True)
    for phrase in sorted_phrases:
        pat = re.compile(re.escape(phrase), re.IGNORECASE)
        result = pat.sub(PHRASE_DICT[phrase], result)

    # Restore protected terms
    result = _restore_terms(result, protected)

    # Check: are there remaining English words that weren't translated?
    temp = result
    # Remove protected terms and Chinese characters to see leftover English
    for term in protected:
        temp = temp.replace(term, "")
    # Remove Chinese chars, punctuation, whitespace, digits
    leftover = re.sub(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\s\d\W]+", " ", temp).strip()
    leftover_words = [w for w in leftover.split() if w.isalpha()]

    if not leftover_words:
        # Full coverage achieved
        if _has_placeholder_artifacts(result):
            return None
        return result
    # Partial coverage → reject to avoid mixed gibberish
    return None


def _passthrough(text: str, short: bool) -> str:
    """
    Return English text as-is.  For longer texts, prefix with [EN] to signal
    that it needs human or online translation.
    Short labels (≤5 words) are returned without prefix since they're
    often navigation items that read fine in English.
    """
    if short:
        return text
    return f"[EN] {text}"


# ─── Quality verification ──────────────────────────────────────────────────

def _verify_translation(source: str, translated: str) -> str:
    """
    Post-translation quality checks.  Returns the (possibly corrected)
    translation, or falls back to passthrough.
    """
    if not source or not source.strip():
        return translated

    # Non-empty source should not produce empty translation
    if not translated or not translated.strip():
        logger.debug("源文本非空但译文为空，改为透传")
        return _passthrough(source, short=(_word_count(source) <= 5))

    # Placeholder artifacts must not remain
    if _has_placeholder_artifacts(translated):
        logger.debug("译文存在占位符残留，改为透传")
        return _passthrough(source, short=(_word_count(source) <= 5))

    return translated


# ─── Statistics tracking ────────────────────────────────────────────────────

class _Stats:
    def __init__(self):
        self.total = 0
        self.online = 0
        self.phrase_match = 0
        self.passthrough_en = 0
        self.cached = 0
        self.errors = 0

    def log_summary(self):
        logger.info(
            "翻译统计：总数=%d，在线=%d，短语匹配=%d，"
            "英文透传=%d，命中内存缓存=%d，错误=%d",
            self.total, self.online, self.phrase_match,
            self.passthrough_en, self.cached, self.errors,
        )


# ─── Main entry point ──────────────────────────────────────────────────────

def translate_entries(
    en_entries: Dict[str, Dict[str, Any]], use_online: bool = False
) -> Dict[str, Dict[str, Any]]:
    """
    Translate all extracted entries from English to Chinese.
    Returns a new dict with the same structure but translated values.
    """
    _load_cache()
    stats = _Stats()

    zh_entries: Dict[str, Dict[str, Any]] = {}
    total_pages = len(en_entries)

    # Collect all unique strings for potential batch online translation
    if use_online:
        _batch_translate_all(en_entries, stats)

    for idx, (path, page_data) in enumerate(en_entries.items(), 1):
        if idx % 50 == 0 or idx == 1:
            logger.info("翻译页面 %d/%d：%s", idx, total_pages, path)
        zh_page: Dict[str, Any] = {}

        for key, value in page_data.items():
            if isinstance(value, str):
                zh_page[key] = _translate_and_track(value, use_online, stats)
            elif isinstance(value, list):
                zh_page[key] = [
                    _translate_and_track(item, use_online, stats)
                    if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                zh_page[key] = value

        zh_entries[path] = zh_page

    _save_cache()
    stats.log_summary()
    return zh_entries


def _translate_and_track(
    text: str, use_online: bool, stats: _Stats
) -> str:
    """Translate one string, update stats, apply quality checks."""
    stats.total += 1
    try:
        stripped = text.strip() if text else ""
        if not stripped or len(stripped) <= 2:
            return text

        # Cache hit?
        cached = _get_cached(stripped)
        if cached is not None:
            stats.cached += 1
            return cached

        # Exact phrase match?
        lower = stripped.lower()
        if lower in _PHRASE_LOWER:
            stats.phrase_match += 1
            result = _PHRASE_LOWER[lower]
            _set_cached(stripped, result)
            return result

        # Online?
        if use_online:
            online_result = _translate_online_protected(stripped)
            if online_result is not None:
                online_result = _verify_translation(stripped, online_result)
                if not online_result.startswith("[EN] "):
                    stats.online += 1
                    _set_cached(stripped, online_result)
                    return online_result

        # Offline phrase-based
        result = _translate_offline(stripped)
        result = _verify_translation(stripped, result)

        if result.startswith("[EN] ") or result == stripped:
            stats.passthrough_en += 1
        else:
            stats.phrase_match += 1

        return result

    except Exception as exc:
        stats.errors += 1
        logger.warning("翻译错误 %r：%s", text[:60], exc)
        return text


def _batch_translate_all(
    en_entries: Dict[str, Dict[str, Any]], stats: _Stats
) -> None:
    """
    Pre-translate all unique strings via batch online translation.
    Results are stored in the cache so individual lookups are instant.
    """
    # Collect unique strings that aren't already cached or phrase-matched
    unique_texts: List[str] = []
    seen: set = set()

    for page_data in en_entries.values():
        for value in page_data.values():
            items: List[str] = []
            if isinstance(value, str):
                items = [value]
            elif isinstance(value, list):
                items = [v for v in value if isinstance(v, str)]
            for item in items:
                s = item.strip()
                if (
                    s
                    and len(s) > 2
                    and s not in seen
                    and _get_cached(s) is None
                    and s.lower() not in _PHRASE_LOWER
                ):
                    unique_texts.append(s)
                    seen.add(s)

    if not unique_texts:
        return

    logger.info("批量在线翻译唯一文本：%d", len(unique_texts))
    batch_size = getattr(config, "TRANSLATE_BATCH_SIZE", 50)
    translated_count = 0

    for i in range(0, len(unique_texts), batch_size):
        batch = unique_texts[i : i + batch_size]
        # Protect terms in each text before sending
        protected_pairs = [_protect_terms(t) for t in batch]
        texts_to_send = [p[0] for p in protected_pairs]

        results = _online_translate_batch(texts_to_send)

        for original, (_, protected), result in zip(batch, protected_pairs, results):
            if result is None:
                continue
            restored = _restore_terms(result, protected)
            if _has_placeholder_artifacts(restored):
                continue
            restored = _verify_translation(original, restored)
            if not restored.startswith("[EN] "):
                _set_cached(original, restored)
                translated_count += 1

        # Rate limit between batches
        time.sleep(config.TRANSLATE_DELAY)
        # Periodic cache save
        if (i // batch_size) % 10 == 9:
            _save_cache()

    logger.info("批量翻译完成：成功 %d / %d", translated_count, len(unique_texts))
    _save_cache()

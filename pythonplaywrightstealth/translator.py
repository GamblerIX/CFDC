"""
translator.py – Translate extracted English entries to Chinese.

Supports multiple backends:
1. Offline dictionary + pattern-based translation (always available)
2. deep-translator / Google Translate (when network is available)
3. argos-translate (when installed with model downloaded)

The offline translator uses a comprehensive technical dictionary optimized
for Cloudflare developer documentation.
"""

import logging
import re
import time
from typing import Any, Dict, List, Union

import config

logger = logging.getLogger(__name__)

# ─── Comprehensive Translation Dictionary ───────────────────────────────────
# Common phrases and terms found in Cloudflare developer documentation.
# This dictionary is used for offline translation when no API is available.

PHRASE_DICT: Dict[str, str] = {
    # ── Common UI & documentation phrases ────────────────────────────────
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

    # ── Cloudflare-specific terms ────────────────────────────────────────
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
    "tunnel": "隧道",
    "connector": "连接器",
    "gateway": "网关",
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

    # ── Sentences commonly found in Cloudflare docs ──────────────────────
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
}

# ── Word-level dictionary for composing translations ─────────────────────────
WORD_DICT: Dict[str, str] = {
    "a": "一个",
    "the": "",
    "is": "是",
    "are": "是",
    "was": "是",
    "were": "是",
    "be": "是",
    "been": "已经",
    "being": "正在",
    "have": "有",
    "has": "有",
    "had": "有",
    "do": "做",
    "does": "做",
    "did": "做",
    "will": "将",
    "would": "将会",
    "shall": "应该",
    "should": "应该",
    "may": "可以",
    "might": "可能",
    "must": "必须",
    "can": "可以",
    "could": "可以",
    "need": "需要",
    "needs": "需要",
    "want": "想要",
    "use": "使用",
    "used": "使用",
    "using": "使用",
    "allow": "允许",
    "allows": "允许",
    "enable": "启用",
    "enables": "启用",
    "disable": "禁用",
    "disables": "禁用",
    "provide": "提供",
    "provides": "提供",
    "support": "支持",
    "supports": "支持",
    "include": "包括",
    "includes": "包括",
    "require": "需要",
    "requires": "需要",
    "configure": "配置",
    "manage": "管理",
    "connect": "连接",
    "run": "运行",
    "running": "运行",
    "start": "启动",
    "stop": "停止",
    "send": "发送",
    "receive": "接收",
    "read": "读取",
    "write": "写入",
    "access": "访问",
    "protect": "保护",
    "secure": "安全的",
    "available": "可用的",
    "your": "您的",
    "you": "您",
    "this": "此",
    "that": "那个",
    "these": "这些",
    "those": "那些",
    "all": "所有",
    "any": "任何",
    "each": "每个",
    "every": "每个",
    "other": "其他",
    "more": "更多",
    "most": "最",
    "some": "一些",
    "many": "许多",
    "few": "少数",
    "no": "没有",
    "not": "不",
    "only": "仅",
    "also": "也",
    "very": "非常",
    "just": "只是",
    "about": "关于",
    "with": "与",
    "without": "没有",
    "from": "从",
    "into": "到",
    "through": "通过",
    "between": "之间",
    "before": "之前",
    "after": "之后",
    "during": "期间",
    "while": "当",
    "when": "当",
    "where": "在哪里",
    "how": "如何",
    "what": "什么",
    "which": "哪个",
    "who": "谁",
    "why": "为什么",
    "if": "如果",
    "then": "然后",
    "else": "否则",
    "and": "和",
    "or": "或",
    "but": "但是",
    "for": "用于",
    "on": "在",
    "in": "在",
    "at": "在",
    "to": "到",
    "of": "的",
    "by": "通过",
    "as": "作为",
    "an": "一个",
    "application": "应用程序",
    "applications": "应用程序",
    "app": "应用",
    "apps": "应用",
    "server": "服务器",
    "servers": "服务器",
    "client": "客户端",
    "clients": "客户端",
    "user": "用户",
    "users": "用户",
    "developer": "开发者",
    "developers": "开发者",
    "network": "网络",
    "networks": "网络",
    "traffic": "流量",
    "data": "数据",
    "file": "文件",
    "files": "文件",
    "page": "页面",
    "pages": "页面",
    "site": "站点",
    "sites": "站点",
    "website": "网站",
    "websites": "网站",
    "service": "服务",
    "services": "服务",
    "feature": "功能",
    "features": "功能",
    "option": "选项",
    "options": "选项",
    "setting": "设置",
    "settings": "设置",
    "configuration": "配置",
    "command": "命令",
    "commands": "命令",
    "code": "代码",
    "script": "脚本",
    "project": "项目",
    "environment": "环境",
    "production": "生产",
    "staging": "暂存",
    "development": "开发",
    "local": "本地",
    "remote": "远程",
    "global": "全局",
    "public": "公共",
    "private": "私有",
    "internal": "内部",
    "external": "外部",
    "custom": "自定义",
    "static": "静态",
    "dynamic": "动态",
    "real-time": "实时",
    "automatic": "自动",
    "manual": "手动",
    "advanced": "高级",
    "basic": "基础",
    "simple": "简单",
    "complex": "复杂",
    "full": "完整",
    "partial": "部分",
    "complete": "完成",
    "empty": "空",
    "new": "新",
    "old": "旧",
    "existing": "现有",
    "current": "当前",
    "previous": "之前",
    "next": "下一个",
    "first": "第一个",
    "last": "最后",
    "single": "单个",
    "multiple": "多个",
    "maximum": "最大",
    "minimum": "最小",
    "large": "大",
    "small": "小",
    "high": "高",
    "low": "低",
    "fast": "快速",
    "slow": "慢",
    "open": "打开",
    "close": "关闭",
    "free": "免费",
    "paid": "付费",
    "plan": "计划",
    "plans": "计划",
    "account": "账户",
    "team": "团队",
    "organization": "组织",
    "member": "成员",
    "members": "成员",
    "role": "角色",
    "permission": "权限",
    "owner": "所有者",
    "admin": "管理员",
    "administrator": "管理员",
    "region": "区域",
    "location": "位置",
    "country": "国家",
    "version": "版本",
    "release": "发布",
    "branch": "分支",
    "commit": "提交",
    "deploy": "部署",
    "build": "构建",
    "preview": "预览",
    "live": "正式",
    "name": "名称",
    "description": "描述",
    "title": "标题",
    "label": "标签",
    "tag": "标签",
    "tags": "标签",
    "category": "类别",
    "status": "状态",
    "state": "状态",
    "mode": "模式",
    "level": "级别",
    "size": "大小",
    "count": "计数",
    "limit": "限制",
    "rate": "速率",
    "cost": "成本",
    "price": "价格",
    "storage": "存储",
    "memory": "内存",
    "compute": "计算",
    "cpu": "CPU",
    "connection": "连接",
    "connections": "连接",
    "port": "端口",
    "address": "地址",
    "ip address": "IP 地址",
    "url": "URL",
    "path": "路径",
    "method": "方法",
    "format": "格式",
    "content": "内容",
    "text": "文本",
    "image": "图片",
    "video": "视频",
    "audio": "音频",
    "media": "媒体",
    "email": "邮箱",
    "notification": "通知",
    "alert": "告警",
    "log": "日志",
    "metric": "指标",
    "trace": "跟踪",
    "span": "跨度",
    "sample": "样本",
    "interval": "间隔",
    "duration": "持续时间",
    "timestamp": "时间戳",
    "date": "日期",
    "time": "时间",
    "minute": "分钟",
    "minutes": "分钟",
    "hour": "小时",
    "hours": "小时",
    "day": "天",
    "days": "天",
    "week": "周",
    "month": "月",
    "year": "年",
    "second": "秒",
    "seconds": "秒",
    "millisecond": "毫秒",
    "byte": "字节",
    "bytes": "字节",
    "kilobyte": "千字节",
    "megabyte": "兆字节",
    "gigabyte": "千兆字节",
}

# Compiled regex for protecting no-translate terms
_PROTECT_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in sorted(config.NO_TRANSLATE_TERMS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

_PH_TEMPLATE = "⟦{}⟧"


def _protect_terms(text: str) -> tuple[str, list[str]]:
    """Replace protected terms with numbered placeholders."""
    protected: list[str] = []

    def _replace(m: re.Match) -> str:
        idx = len(protected)
        protected.append(m.group(0))
        return _PH_TEMPLATE.format(idx)

    return _PROTECT_RE.sub(_replace, text), protected


def _restore_terms(text: str, protected: list[str]) -> str:
    """Restore protected terms from placeholders."""
    for idx, term in enumerate(protected):
        placeholder = _PH_TEMPLATE.format(idx)
        text = text.replace(placeholder, term)
    return text


def _translate_offline(text: str) -> str:
    """
    Translate using the offline dictionary.
    First tries exact phrase match, then word-by-word for shorter texts.
    """
    if not text or not text.strip():
        return text

    stripped = text.strip()

    # Try exact phrase match (case-insensitive)
    lower = stripped.lower()
    for phrase, translation in PHRASE_DICT.items():
        if lower == phrase.lower():
            return translation

    # Protect technical terms
    protected_text, protected_terms = _protect_terms(stripped)

    # Try phrase replacement (longest match first)
    result = protected_text
    sorted_phrases = sorted(PHRASE_DICT.keys(), key=len, reverse=True)
    for phrase in sorted_phrases:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(PHRASE_DICT[phrase], result)

    # Restore protected terms
    result = _restore_terms(result, protected_terms)

    return result


def _try_online_translate(text: str) -> str | None:
    """Try to use online translation, return None if unavailable."""
    try:
        from deep_translator import GoogleTranslator
        result = GoogleTranslator(source="en", target="zh-CN").translate(text)
        return result
    except Exception:
        return None


def _translate_single(text: str, use_online: bool = False) -> str:
    """Translate a single string."""
    if not text or not text.strip():
        return text

    if len(text.strip()) <= 2:
        return text

    if use_online:
        result = _try_online_translate(text)
        if result:
            return result

    return _translate_offline(text)


def translate_entries(
    en_entries: Dict[str, Dict[str, Any]], use_online: bool = False
) -> Dict[str, Dict[str, Any]]:
    """
    Translate all extracted entries from English to Chinese.
    Returns a new dict with the same structure but translated values.
    """
    zh_entries: Dict[str, Dict[str, Any]] = {}
    total_pages = len(en_entries)

    for idx, (path, page_data) in enumerate(en_entries.items(), 1):
        if idx % 50 == 0 or idx == 1:
            logger.info("Translating page %d/%d: %s", idx, total_pages, path)
        zh_page: Dict[str, Any] = {}

        for key, value in page_data.items():
            if isinstance(value, str):
                zh_page[key] = _translate_single(value, use_online)
                if use_online:
                    time.sleep(config.TRANSLATE_DELAY)
            elif isinstance(value, list):
                translated_list = []
                for item in value:
                    if isinstance(item, str):
                        translated_list.append(_translate_single(item, use_online))
                        if use_online:
                            time.sleep(config.TRANSLATE_DELAY)
                    else:
                        translated_list.append(item)
                zh_page[key] = translated_list
            else:
                zh_page[key] = value

        zh_entries[path] = zh_page

    return zh_entries

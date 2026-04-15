"""CFDC 抓取与翻译配置。"""

import os

# ── 抓取配置 ───────────────────────────────────────────────────────────────
BASE_URL = "https://developers.cloudflare.com"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"

# 抓取页面上限（0 表示不限制）
MAX_PAGES = 0

# 浏览器并发页数
CONCURRENCY = 4

# 页面加载超时时间（毫秒）
PAGE_TIMEOUT_MS = 30_000

# 页面访问间隔（秒）
CRAWL_DELAY = 0.5

# ── 路径配置 ───────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
I18N_DIR = os.path.join(PROJECT_ROOT, "i18n")
EN_JSON_PATH = os.path.join(I18N_DIR, "en.json")
ZH_CN_JSON_PATH = os.path.join(I18N_DIR, "zh-cn.json")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
URLS_JSON_PATH = os.path.join(SCRIPT_DIR, "urls.json")
ENTRIES_JSON_PATH = os.path.join(SCRIPT_DIR, "entries.json")
VALIDATION_REPORT_PATH = os.path.join(SCRIPT_DIR, "validation_report.json")

# ── 翻译配置 ───────────────────────────────────────────────────────────────
TRANSLATE_DELAY = 0.3
TRANSLATE_BATCH_SIZE = 50

# 不应翻译的术语
NO_TRANSLATE_TERMS = {
    "Cloudflare", "Workers", "Workers AI", "KV", "R2", "D1", "Pages", "Wrangler",
    "Durable Objects", "Hyperdrive", "Queues", "Vectorize", "Constellation", "Turnstile",
    "Zaraz", "Snippets", "Stream", "Images", "Calls", "AI Gateway", "Zero Trust", "Access",
    "Tunnel", "Gateway", "WARP", "Magic WAN", "Magic Transit", "Magic Firewall", "Spectrum",
    "Argo", "Load Balancing", "SSL/TLS", "DNS", "DNSSEC", "Registrar", "Terraform", "Pulumi",
    "API", "REST", "GraphQL", "SDK", "CLI", "JSON", "HTML", "CSS", "JavaScript", "TypeScript",
    "Python", "Rust", "Go", "C", "npm", "Node.js", "Cron", "WebSocket", "WebSockets", "HTTP",
    "HTTPS", "TCP", "UDP", "TLS", "SSH", "CDN", "WAF", "DDoS", "Bot Management", "Cache",
    "Railgun", "Pub/Sub", "Email Routing", "Area 1", "CASB", "DLP", "DEX", "Waiting Room",
    "Web Analytics", "Logpush", "Logpull",
}

# ── URL 过滤 ───────────────────────────────────────────────────────────────
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".pdf", ".zip", ".tar", ".gz",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
    ".mp4", ".webm", ".mp3",
    ".xml", ".json", ".txt", ".csv",
}

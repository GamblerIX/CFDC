"""Global configuration for the CFDC crawler and translator."""

import os

# ── Crawling ────────────────────────────────────────────────────────────────
BASE_URL = "https://developers.cloudflare.com"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"

# Maximum number of pages to crawl (set to 0 for unlimited)
MAX_PAGES = 0

# Concurrent browser pages for crawling
CONCURRENCY = 4

# Page load timeout in milliseconds
PAGE_TIMEOUT_MS = 30_000

# Delay between page loads (seconds) to be polite
CRAWL_DELAY = 0.5

# ── Paths ───────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
I18N_DIR = os.path.join(PROJECT_ROOT, "i18n")
EN_JSON_PATH = os.path.join(I18N_DIR, "en.json")
ZH_CN_JSON_PATH = os.path.join(I18N_DIR, "zh-cn.json")
URLS_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "urls.json"
)
ENTRIES_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "entries_cache.json"
)

# ── Translation ─────────────────────────────────────────────────────────────
# Delay between translation requests (seconds)
TRANSLATE_DELAY = 0.3

# Batch size for translation
TRANSLATE_BATCH_SIZE = 50

# Terms that should NOT be translated (kept as-is)
NO_TRANSLATE_TERMS = {
    "Cloudflare",
    "Workers",
    "Workers AI",
    "KV",
    "R2",
    "D1",
    "Pages",
    "Wrangler",
    "Durable Objects",
    "Hyperdrive",
    "Queues",
    "Vectorize",
    "Constellation",
    "Turnstile",
    "Zaraz",
    "Snippets",
    "Stream",
    "Images",
    "Calls",
    "AI Gateway",
    "Zero Trust",
    "Access",
    "Tunnel",
    "Gateway",
    "WARP",
    "Magic WAN",
    "Magic Transit",
    "Magic Firewall",
    "Spectrum",
    "Argo",
    "Load Balancing",
    "SSL/TLS",
    "DNS",
    "DNSSEC",
    "Registrar",
    "Terraform",
    "Pulumi",
    "API",
    "REST",
    "GraphQL",
    "SDK",
    "CLI",
    "JSON",
    "HTML",
    "CSS",
    "JavaScript",
    "TypeScript",
    "Python",
    "Rust",
    "Go",
    "C",
    "npm",
    "Node.js",
    "Cron",
    "WebSocket",
    "WebSockets",
    "HTTP",
    "HTTPS",
    "TCP",
    "UDP",
    "TLS",
    "SSH",
    "CDN",
    "WAF",
    "DDoS",
    "Bot Management",
    "Cache",
    "Railgun",
    "Pub/Sub",
    "Email Routing",
    "Area 1",
    "CASB",
    "DLP",
    "DEX",
    "Waiting Room",
    "Web Analytics",
    "Logpush",
    "Logpull",
}

# ── URL Filters ─────────────────────────────────────────────────────────────
# File extensions to skip during crawling
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".pdf", ".zip", ".tar", ".gz",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
    ".mp4", ".webm", ".mp3",
    ".xml", ".json", ".txt", ".csv",
}

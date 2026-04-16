// ==UserScript==
// @name         CFDC
// @namespace    http://github.com/GamblerIX/
// @version      2026-04-16.2
// @description  将 Cloudflare Developers 文档优先替换为中文词条。
// @author       GamblerIX
// @match        https://developers.cloudflare.com/*
// @icon         https://raw.githubusercontent.com/GamblerIX/CFDC/refs/heads/main/favicon.png
// @grant        GM_xmlhttpRequest
// @grant        GM.xmlHttpRequest
// @connect      raw.githubusercontent.com
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  const DICT_URLS = [
    {
      name: 'userscript',
      en: 'https://raw.githubusercontent.com/GamblerIX/CFDC/main/i18n/userscript-en.json',
      zh: 'https://raw.githubusercontent.com/GamblerIX/CFDC/main/i18n/userscript-zh-cn.json',
    },
    {
      name: 'full',
      en: 'https://raw.githubusercontent.com/GamblerIX/CFDC/main/i18n/en.json',
      zh: 'https://raw.githubusercontent.com/GamblerIX/CFDC/main/i18n/zh-cn.json',
    },
  ];

  const CACHE_KEY = 'cfdc_i18n_map_v3';
  const CACHE_TTL_MS = 6 * 60 * 60 * 1000; // 6 小时

  const logger = {
    info: (...args) => console.info('[CFDC]', ...args),
    warn: (...args) => console.warn('[CFDC]', ...args),
    error: (...args) => console.error('[CFDC]', ...args),
  };

  const textNodes = new Set();

  function isPlainObject(value) {
    return value && typeof value === 'object' && !Array.isArray(value);
  }

  function collectTranslations(enNode, zhNode, map) {
    if (typeof enNode === 'string' && typeof zhNode === 'string') {
      const source = enNode.trim();
      const translated = zhNode.trim();
      if (source && translated && !translated.startsWith('[EN]')) {
        map[source] = translated;
      }
      return;
    }

    if (Array.isArray(enNode) && Array.isArray(zhNode)) {
      const len = Math.min(enNode.length, zhNode.length);
      for (let i = 0; i < len; i += 1) {
        collectTranslations(enNode[i], zhNode[i], map);
      }
      return;
    }

    if (isPlainObject(enNode) && isPlainObject(zhNode)) {
      for (const [key, value] of Object.entries(enNode)) {
        if (!(key in zhNode)) continue;
        collectTranslations(value, zhNode[key], map);
      }
    }
  }

  function safeJsonParse(raw) {
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  function loadCache() {
    const cachedRaw = localStorage.getItem(CACHE_KEY);
    if (!cachedRaw) return null;

    const cached = safeJsonParse(cachedRaw);
    if (!cached || !cached.expireAt || !cached.map) return null;

    if (Date.now() > cached.expireAt) {
      localStorage.removeItem(CACHE_KEY);
      return null;
    }

    return cached;
  }

  function saveCache(dictName, map) {
    const payload = {
      expireAt: Date.now() + CACHE_TTL_MS,
      dictName,
      map,
    };
    localStorage.setItem(CACHE_KEY, JSON.stringify(payload));
  }

  function request(url) {
    return new Promise((resolve, reject) => {
      const requestFn =
        typeof GM_xmlhttpRequest === 'function'
          ? GM_xmlhttpRequest
          : (typeof GM !== 'undefined' && typeof GM.xmlHttpRequest === 'function' ? GM.xmlHttpRequest : null);

      if (!requestFn) {
        reject(new Error('缺少 GM_xmlhttpRequest 权限，无法跨域加载词典。'));
        return;
      }

      requestFn({
        method: 'GET',
        url,
        onload: (res) => {
          if (res.status >= 200 && res.status < 300) {
            resolve(res.responseText);
          } else {
            reject(new Error(`请求失败：${url} (HTTP ${res.status})`));
          }
        },
        onerror: () => reject(new Error(`网络错误：${url}`)),
      });
    });
  }

  async function loadDictionaryPair(dict) {
    const [enRaw, zhRaw] = await Promise.all([request(dict.en), request(dict.zh)]);
    const en = safeJsonParse(enRaw);
    const zh = safeJsonParse(zhRaw);

    if (!en || !zh || typeof en !== 'object' || typeof zh !== 'object') {
      throw new Error(`${dict.name} 词典文件格式异常。`);
    }

    const map = {};
    collectTranslations(en, zh, map);

    if (!Object.keys(map).length) {
      throw new Error(`${dict.name} 没有可用词条。`);
    }

    return map;
  }

  async function loadI18nMap() {
    const cache = loadCache();
    if (cache) {
      logger.info(`已加载缓存词条：${Object.keys(cache.map).length} 项（${cache.dictName || 'unknown'}）`);
      return cache.map;
    }

    let lastError = null;

    for (const dict of DICT_URLS) {
      try {
        const map = await loadDictionaryPair(dict);
        saveCache(dict.name, map);
        logger.info(`词典加载完成：${Object.keys(map).length} 项（${dict.name}）`);
        return map;
      } catch (error) {
        lastError = error;
        logger.warn(`词典加载失败（${dict.name}），尝试下一个。`, error);
      }
    }

    throw lastError || new Error('无法加载可用词典。');
  }

  function walkTextNodes(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        const parent = node.parentElement;
        if (!parent) return NodeFilter.FILTER_REJECT;
        if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA', 'CODE', 'PRE'].includes(parent.tagName)) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });

    let current;
    while ((current = walker.nextNode())) {
      textNodes.add(current);
    }
  }

  function replaceTextInNode(node, map) {
    const content = node.nodeValue;
    if (!content) return;

    const leading = content.match(/^\s*/)?.[0] ?? '';
    const trailing = content.match(/\s*$/)?.[0] ?? '';
    const core = content.trim();
    if (!core) return;

    const translated = map[core];
    if (!translated || translated === core) return;

    node.nodeValue = `${leading}${translated}${trailing}`;
  }

  function applyTranslations(map) {
    walkTextNodes(document.body);
    textNodes.forEach((node) => replaceTextInNode(node, map));
  }

  function observeDom(map) {
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        mutation.addedNodes.forEach((added) => {
          if (added.nodeType === Node.TEXT_NODE) {
            replaceTextInNode(added, map);
            return;
          }
          if (added.nodeType === Node.ELEMENT_NODE) {
            walkTextNodes(added);
          }
        });
      }
      textNodes.forEach((node) => replaceTextInNode(node, map));
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }

  async function main() {
    try {
      const map = await loadI18nMap();
      applyTranslations(map);
      observeDom(map);
      logger.info('翻译已启用。');
    } catch (error) {
      logger.error('初始化失败：', error);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', main, { once: true });
  } else {
    main();
  }
})();

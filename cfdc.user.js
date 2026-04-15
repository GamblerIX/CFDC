// ==UserScript==
// @name         CFDC
// @namespace    http://github.com/GamblerIX/
// @version      2026-04-15
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

  const EN_URL = 'https://raw.githubusercontent.com/GamblerIX/CFDC/main/i18n/en.json';
  const ZH_URL = 'https://raw.githubusercontent.com/GamblerIX/CFDC/main/i18n/zh-cn.json';
  const CACHE_KEY = 'cfdc_i18n_map_v1';
  const CACHE_TTL_MS = 6 * 60 * 60 * 1000; // 6 小时

  const logger = {
    info: (...args) => console.info('[CFDC]', ...args),
    warn: (...args) => console.warn('[CFDC]', ...args),
    error: (...args) => console.error('[CFDC]', ...args),
  };

  const textNodes = new Set();

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
    return cached.map;
  }

  function saveCache(map) {
    const payload = {
      expireAt: Date.now() + CACHE_TTL_MS,
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

  async function loadI18nMap() {
    const cache = loadCache();
    if (cache) {
      logger.info(`已加载缓存词条：${Object.keys(cache).length} 项`);
      return cache;
    }

    const [enRaw, zhRaw] = await Promise.all([request(EN_URL), request(ZH_URL)]);
    const en = safeJsonParse(enRaw);
    const zh = safeJsonParse(zhRaw);

    if (!en || !zh || typeof en !== 'object' || typeof zh !== 'object') {
      throw new Error('词典文件格式异常。');
    }

    const map = {};
    for (const [key, value] of Object.entries(en)) {
      const source = String(value || '').trim();
      const translated = String(zh[key] || '').trim();
      if (!source || !translated || translated.startsWith('[EN]')) continue;
      map[source] = translated;
    }

    if (!Object.keys(map).length) {
      throw new Error('没有可用词条。');
    }

    saveCache(map);
    logger.info(`词典加载完成：${Object.keys(map).length} 项`);
    return map;
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
    let content = node.nodeValue;
    let changed = false;

    for (const [from, to] of Object.entries(map)) {
      if (!content.includes(from)) continue;
      content = content.split(from).join(to);
      changed = true;
    }

    if (changed) {
      node.nodeValue = content;
    }
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

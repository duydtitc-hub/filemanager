const fs = require('fs').promises;
const path = require('path');
const puppeteer = require('puppeteer');

function sleep(ms){ return new Promise(r=>setTimeout(r, ms)); }
async function wait(ms, page){
  if (page && typeof page.waitForTimeout === 'function') return page.waitForTimeout(ms);
  return sleep(ms);
}

// Global action delay (ms) to slow automated interactions slightly
const ACTION_DELAY_MS = 300;

// Retry helper for selectors with a delay between attempts
async function retryFind(page, selector, attempts = 6, delayMs = ACTION_DELAY_MS) {
  for (let i = 0; i < attempts; i++) {
    try {
      const handle = await page.$(selector).catch(() => null);
      if (handle) return handle;
    } catch (e) {}
    await wait(delayMs, page);
  }
  return null;
}

async function loadCookies(page, cookiesPath) {
  try {
    
    const data = await fs.readFile(cookiesPath, 'utf8');
    const cookies = JSON.parse(data);
    if (!Array.isArray(cookies)) return;
    await page.setCookie(...cookies);
    console.log('Loaded cookies:', cookiesPath);
  } catch (err) {
    console.warn('No cookies loaded:', err.message);
  }
}

async function upload({ videoPath, caption, tags, cookiesPath, headless }) {
  if (!videoPath) throw new Error('videoPath is required');
  // Default to a hard-coded cookies file in the workspace root if not provided
  try {
    cookiesPath=   path.join(__dirname, 'cookies.json');
    const defaultCookies = path.join(__dirname, 'cookies.json');
    if (!cookiesPath) cookiesPath = defaultCookies;
  } catch (e) {
    // ignore path resolution errors and fall back to provided cookiesPath
  }

  const browser = await puppeteer.launch({
    headless:true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage'
    ]
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });

    if (cookiesPath) await loadCookies(page, cookiesPath);

    // Go to upload page
    await page.goto('https://www.tiktok.com/tiktokstudio/upload?from=creator_center', { waitUntil: 'networkidle2', timeout: 120000 });
    await wait(ACTION_DELAY_MS, page);

    // After injecting cookies, reload to apply session
    if (cookiesPath) {
      await page.reload({ waitUntil: 'networkidle2', timeout: 120000 });
      await wait(ACTION_DELAY_MS, page);
    }

    // Wait for file input (retry until found). Use `retryFind` to be resilient to slow-loading UIs.
    const input = await retryFind(page, 'input[type=file]', 30, 1000);
    if (!input) {
      console.error('Upload input not found after retries. Are you logged in?');
      return;
    }

    const absoluteVideo = path.resolve(videoPath);
    await input.uploadFile(absoluteVideo);
    console.log('Video attached:', absoluteVideo);
    await wait(ACTION_DELAY_MS, page);

    // Wait for upload to complete — either progress reaches 100% or the Post button becomes enabled
    async function waitForUploadComplete(page, timeoutMs = 300000) {
      const preferredPostSelector = 'button:enabled, [role="button"]:not([aria-disabled="true"])';
      try {
        await page.waitForFunction((preferred) => {
          // check progress bar
          const p = document.querySelector('.info-progress.success');
          if (p) {
            const inline = p.getAttribute('style') || '';
            if (/width\s*:\s*100%/.test(inline)) return true;
            const txt = (p.textContent || '').trim();
            if (txt.includes('100%')) return true;
            const parent = p.parentElement;
            if (parent) {
              const pw = parent.getBoundingClientRect().width;
              const ew = p.getBoundingClientRect().width;
              if (pw > 0 && Math.abs(ew - pw) < 2) return true;
            }
          }

          // check preferred Post button enabling (search for Button__content with 'post' text and find ancestor button)
          const candidates = Array.from(document.querySelectorAll('.Button__content')) || [];
          for (const c of candidates) {
            if (!c || !(c.textContent || '').toLowerCase().includes('post')) continue;
            const btn = c.closest('button, [role="button"], a');
            if (!btn) continue;
            const aria = btn.getAttribute && btn.getAttribute('aria-disabled');
            if (aria === 'true') continue;
            const disabled = btn.disabled || btn.hasAttribute('disabled');
            if (!disabled) return true;
          }

          // generic enabled button exists containing 'post'
          const all = Array.from(document.querySelectorAll('button, [role="button"], a'));
          for (const el of all) {
            try {
              if ((el.textContent || '').toLowerCase().includes('post')) {
                const aria = el.getAttribute && el.getAttribute('aria-disabled');
                if (aria === 'true') continue;
                if (el.disabled || el.hasAttribute('disabled')) continue;
                return true;
              }
            } catch (e) {}
          }

          return false;
        }, { timeout: timeoutMs }, preferredPostSelector);
        return true;
      } catch (err) {
        return false;
      }
    }

    const uploadOk = await waitForUploadComplete(page, 300000);
    if (!uploadOk) console.warn('Upload did not report 100% within timeout — proceeding cautiously.');

    // Prepare caption (description) and tags separately
    const captionOnly = caption || '';
    const normalizedTags = Array.isArray(tags) ? tags.slice(0,5).map(t => String(t).trim().replace(/^#+/, '').replace(/\s+/g,'')).filter(Boolean) : [];

    // First try Draft.js editor used by TikTok (contenteditable)
    const draftSelector = '.notranslate.public-DraftEditor-content[contenteditable="true"], .public-DraftEditor-content[contenteditable="true"]';
    let captionSet = false;
    let usedDraftEditor = false;
    const draftEl = await retryFind(page, draftSelector, 6, ACTION_DELAY_MS);
    if (draftEl) {
      try {
        // Instead of complex DOM removals, count filename length and send Backspace
        // keystrokes equal to (filename length + 8) to remove any pasted filename text.
        const videoBase = path.basename(videoPath || '');
        const videoNameNoExt = (videoBase || '').replace(/\.[^/.]+$/, '');
        const numToBackspace = (videoNameNoExt || '').length + 8;

        await draftEl.focus();
        await wait(ACTION_DELAY_MS, page);
        try {
          for (let i = 0; i < numToBackspace; i++) {
            await page.keyboard.press('Backspace');
            await wait(40, page);
          }
          // Also attempt Delete to ensure any leftover characters are removed
          for (let i = 0; i < numToBackspace; i++) {
            await page.keyboard.press('Delete');
            await wait(40, page);
          }
        } catch (e) {
          // ignore keyboard failures; proceed to typing
        }
        if (captionOnly) await page.keyboard.type(captionOnly);
        if (normalizedTags.length) {
          await page.keyboard.press('Enter');
          await wait(80, page);
          for (const t of normalizedTags) {
            const tagText = `#${t}`;
            try {
              await page.keyboard.type(tagText);
              await wait(120, page);
              // separate tags with a space instead of pressing Enter each time
              await page.keyboard.type(' ');
              await wait(80, page);
            } catch (e) {
              // if typing a tag fails, continue with remaining tags
            }
          }
        }
        await wait(300, page);
        captionSet = true;
        usedDraftEditor = true;
        console.log('Caption set using Draft editor', draftSelector);
      } catch (e) {
        console.warn('Failed to set caption via Draft editor, fallback to selectors:', e.message);
      }
    }

    // Fallback: Attempt to set caption with common selectors
    if (!captionSet) {
      const captionSelectors = [
        'textarea[placeholder*="Describe"]',
        'textarea',
        '[data-e2e="caption-input"]',
        '[contenteditable="true"]'
      ];
      for (const sel of captionSelectors) {
        const el = await page.$(sel).catch(() => null);
        if (!el) continue;
        try {
          await el.focus();
          await page.evaluate((s, c) => {
            const el = document.querySelector(s);
            if (!el) return;
            if (el.tagName.toLowerCase() === 'textarea') el.value = c;
            else el.innerText = c;
            el.dispatchEvent(new Event('input', { bubbles: true }));
          }, sel, captionOnly || '');
          await wait(300, page);
          captionSet = true;
          console.log('Caption set using', sel);
          break;
        } catch (e) {
          // ignore and continue
        }
      }
    }

    if (!captionSet) console.warn('Could not set caption automatically; you may need to set it manually in the page UI.');

    // Ensure caption field contains description and tags when Draft editor wasn't used
    if (normalizedTags.length && captionSet && !usedDraftEditor) {
      const tagLine = normalizedTags.map(t => `#${t}`).join(' ');
      const combined = captionOnly ? `${captionOnly}\n${tagLine}` : tagLine;
      try {
        await page.evaluate((sels, text) => {
          for (const sel of sels) {
            const el = document.querySelector(sel);
            if (!el) continue;
            if (el.tagName.toLowerCase() === 'textarea') el.value = text;
            else el.innerText = text;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            break;
          }
        }, captionSelectors, combined);
        await wait(300, page);
        console.log('Set caption with tags each on their own line (fallback)');
      } catch (e) {
        console.warn('Failed to set combined caption and tags:', e.message);
      }
    }

    // Before publishing: require music copyright check to be OK
    async function waitForMusicClear(page, timeoutMs = 120000) {
      try {
        await page.waitForFunction(() => {
          const root = document.querySelector('.copyright-check') || document.querySelector('[data-e2e="copyright_container"]');
          if (!root) return false;
          if (root.querySelector('.status-result.status-success')) return true;
          const sw = root.querySelector('.Switch__content[aria-checked="true"], .Switch__root--checked-true');
          if (sw) return true;
          const text = (root.textContent || '').toLowerCase();
          if (text.includes('no issues found') || text.includes('no issues')) return true;
          return false;
        }, { timeout: timeoutMs });
        return true;
      } catch (err) {
        return false;
      }
    }

    const musicOk = await waitForMusicClear(page, 120000);
    if (!musicOk) {
      console.warn('Music copyright check did not clear within timeout — aborting auto-publish.');
      await wait(1000, page);
      await browser.close();
      return;
    }

    // Try to click any element containing the text 'post' (case-insensitive)
    // This finds visible elements containing 'post' and clicks their nearest clickable ancestor.
      // Prefer exact Button__content with full class set and exact text 'Post'
      try {
        await wait(ACTION_DELAY_MS, page);
        const preferredSelectors = [
          '.Button__content.Button__content--shape-default.Button__content--size-large.Button__content--type-primary.Button__content--loading-false',
          '.Button__content.Button__content--shape-default.Button__content--size-large.Button__content--type-primary',
          '.Button__content.Button__content--type-primary'
        ];

        let clicked = false;
        for (const sel of preferredSelectors) {
          const handle = await page.evaluateHandle((s) => {
            const list = Array.from(document.querySelectorAll(s || ''));
            for (const el of list) {
              if (el && (el.textContent || '').trim().toLowerCase() === 'post') return el;
            }
            return null;
          }, sel);

          const el = handle && handle.asElement ? handle.asElement() : null;
          if (el) {
            try {
              await el.evaluate(e => {
                const btn = e.closest && e.closest('button, [role="button"], a');
                (btn || e).click();
              });
              await wait(300, page);
              console.log('Clicked preferred Post button by selector', sel);
              clicked = true;
            } catch (err) {
              console.warn('Failed clicking preferred selector', sel, err.message);
            } finally {
              await handle.dispose();
            }
            if (clicked) break;
          } else {
            if (handle) await handle.dispose();
          }
        }

        if (!clicked) {
          // Fallback: find the first element whose visible text contains 'post' (case-insensitive)
          const postXpath = "//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'post') and (self::div or self::button or self::span or self::a)]";
          const handle2 = await page.evaluateHandle((xp) => {
            const r = document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
            return r.singleNodeValue || null;
          }, postXpath);
          const el2 = handle2 && handle2.asElement ? handle2.asElement() : null;
          if (el2) {
            try {
              await el2.evaluate(e => {
                const btn = e.closest && e.closest('button, [role="button"], a');
                (btn || e).click();
              });
              await wait(ACTION_DELAY_MS + 200, page);
              console.log('Clicked fallback post element');
              clicked = true;
            } catch (err) {
              console.warn('Failed to click fallback post element:', err.message);
            } finally {
              await handle2.dispose();
            }
          } else {
            if (handle2) await handle2.dispose();
            console.warn('No element containing "post" found. Please publish manually.');
          }
        }
      } catch (e) {
        console.warn('Error searching for post element:', e.message);
      }

    // After initial publish click: look for a secondary confirmation 'Post now' button and click it
    try {
      await wait(500, page);
      const confirmSelector = 'button.TUXButton.TUXButton--primary, button.TUXButton--primary';
      const confirmHandle = await page.$(confirmSelector).catch(() => null);
      if (confirmHandle) {
        try {
          const txt = await confirmHandle.evaluate(el => (el.innerText || el.textContent || '').trim());
          if (txt && txt.toLowerCase().includes('post now')) {
            await wait(120, page);
            await confirmHandle.evaluate(b => b.click());
            await wait(ACTION_DELAY_MS, page);
            console.log('Clicked confirmation "Post now" button');
          }
        } catch (e) {
          console.warn('Error clicking confirmation button:', e.message);
        } finally {
          try { await confirmHandle.dispose(); } catch (e) {}
        }
      } else {
        // fallback: try xpath search for button containing 'Post now'
        try {
          const xp = "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'post now')]";
          const h = await page.evaluateHandle(xpStr => {
            const r = document.evaluate(xpStr, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
            return r.singleNodeValue || null;
          }, xp);
          const el2 = h && h.asElement ? h.asElement() : null;
          if (el2) {
            await el2.evaluate(b => b.click());
            await wait(300, page);
            console.log('Clicked confirmation "Post now" button (xpath)');
          }
          if (h) await h.dispose();
        } catch (e) {
          // ignore
        }
      }
    } catch (e) {
      console.warn('Error handling Post now confirmation:', e.message);
    }

    // Wait a short while for any server response / navigation
    await wait(5000, page);
    console.log('Upload script finished. Check the browser to confirm publish state.');
  } finally {
    await browser.close();
  }
 }

function parseArgs() {
  const argv = process.argv.slice(2);
  const out = { headless: true };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--no-headless') { out.headless = false; continue; }
    if (a === '--tags') { const raw = argv[++i] || ''; const parts = raw.includes(',') ? raw.split(',') : raw.split(/\s+/); out.tags = parts.map(p=>p.trim()).filter(Boolean).slice(0,5); continue; }
    if (!out.videoPath) { out.videoPath = a; continue; }
    if (!out.caption) { out.caption = a; continue; }
  }
  return out;
}

if (require.main === module) {
  const args = parseArgs();
  if (!args.videoPath) {
    console.log('Usage: node upload.js <videoPath> [caption] [--tags "tag1,tag2"] [--no-headless]');
    process.exit(1);
  }
  upload(args).catch(err => {
    console.error('Error during upload:', err);
    process.exit(2);
  });
}

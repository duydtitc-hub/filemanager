const fs = require('fs').promises;
const puppeteer = require('puppeteer');

(async () => {
  // 🔗 CONNECT vào Chrome thật
  const browser = await puppeteer.connect({
    browserURL: 'http://localhost:9222',
    defaultViewport: null
  });

  // Lấy tab đang mở hoặc tạo mới
  const pages = await browser.pages();
  const page = pages[0] || await browser.newPage();

  try {
    await page.goto('https://www.tiktok.com/login', {
      waitUntil: 'networkidle2'
    });
  } catch (e) {
    // ignore navigation errors
  }

  console.log('👉 Chrome thật đã mở.');
  console.log('👉 Hãy login TikTok thủ công trong trình duyệt.');
  console.log('👉 Sau khi login xong, quay lại terminal và nhấn ENTER để lưu cookie.');

  // ⏸️ Chờ user nhấn Enter
  await new Promise((resolve) => {
    process.stdin.resume();
    process.stdin.once('data', () => resolve());
  });

  // 🍪 Lấy cookie
  const cookies = await page.cookies();
  await fs.writeFile('cookies.json', JSON.stringify(cookies, null, 2));

  console.log(`✅ Saved ${cookies.length} cookies to cookies.json`);

  // ❗ Không đóng Chrome thật
  await browser.disconnect();
  process.exit(0);
})();

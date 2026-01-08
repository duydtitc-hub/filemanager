# TikTok Uploader (Puppeteer)

Small Node.js script that uses Puppeteer to attach and publish a video on TikTok's web upload page.

Important notes:
- You must be logged in to TikTok. The script supports loading a cookies JSON export (see below).
- Automating uploads may trigger captchas / 2FA or be blocked by TikTok. This script does not bypass those protections.

Usage

1. Install deps:

```bash
npm install
```

2. Export cookies from a logged-in browser for tiktok.com and save them to `cookies.json` (format: an array of cookie objects).

3. Run the script:

```bash
node upload.js path/to/video.mp4 "Your caption here" --cookies cookies.json
```

If TikTok shows additional checks or requires extra UI interaction, you may need to run with `--no-headless` to observe and complete them:

```bash
node upload.js path/to/video.mp4 "Caption" --cookies cookies.json --no-headless
```

Files
- `upload.js` : main script
- `config.example.json` : example config

If you want, I can help: export cookie steps, test a run, or add credential-based login (note: login flows often require captcha/2FA). 

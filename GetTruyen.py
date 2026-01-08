import requests
from bs4 import BeautifulSoup
import re
import time
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
import hashlib
def url_hash(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()

import os
import re
import time
import requests
from bs4 import BeautifulSoup
from DiscordMethod import send_discord_message
CACHE_DIR = "cache"

def url_hash(u: str):
    import hashlib
    return hashlib.md5(u.encode("utf-8")).hexdigest()

def get_novel_text_laophatgia(url: str, delay: float = 1.0) -> str:
    """
    Cào toàn bộ nội dung truyện từ laophatgia.net (dạng mới có danh sách chương trong <ul>).
    Bao gồm tóm tắt ở đầu truyện từ <div class="summary__content">
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, f"{url_hash(url)}.txt")
    cacheSumary = os.path.join(CACHE_DIR, f"sumary_{url_hash(url)}.txt")
 
    # 🔹 Dùng cache nếu có
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                sumary ="";
                send_discord_message(f"📦 Dùng cache: {cache_file}")
                if os.path.exists(cacheSumary):
                    with open(cacheSumary, "r", encoding="utf-8") as s:
                        sumary = s.read().strip()
                                             
                return content,sumary
    all_texts = ""

    def fetch_html(u):
        resp = requests.get(u, timeout=20)
        resp.encoding = "utf-8"
        resp.raise_for_status()
        return resp.text

    # 🔹 Lấy HTML trang chính
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    # 🔹 Lấy tóm tắt truyện (summary)
    summary_container = soup.select_one("div.summary__content")
    paragraphs = []
    for p in summary_container.find_all("p"):
        # Nếu toàn bộ <p> chỉ chứa <strong>, bỏ qua
        if p.find("strong") and len(p.get_text(strip=True)) == len(p.find("strong").get_text(strip=True)):
            continue
        text = p.get_text(" ", strip=True)
        if text:
            paragraphs.append(text)
    summary_text = "\n\n".join(paragraphs).strip()
    # 🔹 Lấy danh sách chương
    chapter_items = soup.select("ul.main.version-chap.no-volumn li.wp-manga-chapter a")
    if not chapter_items:
        raise Exception("❌ Không tìm thấy danh sách chương trong trang laophatgia.net")

    chapter_links = []
    for a in chapter_items:
        link = a.get("href")
        name = a.get_text(strip=True)
        if link and name:
            chapter_links.append({"name": name, "url": link})

    # Trang liệt kê ngược: Chương mới nhất trước, cần đảo lại thứ tự
    chapter_links.reverse()
    send_discord_message(f"📚 Tổng số chương tìm thấy: {len(chapter_links)}")

    # 🔹 Cào nội dung từng chương
    for i, chap in enumerate(chapter_links, start=1):
        try:
          
            chap_html = fetch_html(chap["url"])
            chap_soup = BeautifulSoup(chap_html, "html.parser")

            container = (
                chap_soup.select_one("div.reading-content div.text-left")
                or chap_soup.select_one("div.reading-content")
            )

            if not container:
                send_discord_message("❌ Không tìm thấy nội dung trong chương này.")
                continue

            paragraphs = []
            for p in container.find_all(["p", "div"]):
                text = p.get_text(" ", strip=True)
                if not text:
                    continue
                # Chỉ loại bỏ những câu chứa URL/domain/watermark — không vứt cả <p>
                try:
                    sentences = re.split(r"(?<=[\.!?。！？])\s+", text)
                except Exception:
                    sentences = [text]

                kept = []
                for s in sentences:
                    if not s:
                        continue
                    # Nếu câu chỉ chứa số -> bỏ
                    if re.fullmatch(r"\s*\d+[\.:\)\-]?\s*", s):
                        continue
                    # Nếu câu bắt đầu bằng số đánh thứ tự (ví dụ "1. ..."), xóa phần đánh số và giữ phần sau
                    s_stripped = re.sub(r"^\s*\d+[\.:\)\-]\s*", "", s)
                    if not s_stripped or not s_stripped.strip():
                        # nếu sau khi bỏ tiền tố không còn nội dung thì bỏ câu
                        continue
                    s = s_stripped
                    if re.search(r"laophatgia|https?://|nguồn|facebook|\.net|\.com|\.vn", s, re.I):
                        continue
                    kept.append(s.strip())

                if kept:
                    paragraphs.append(" ".join(kept))

            clean_text = "\n\n".join(paragraphs)
            # Xóa "Chương X" ở đầu dòng hoặc đoạn
            clean_text = re.sub(r"(?im)^(chương|chuong)\s*\d+[\.:–-]?\s*", "", clean_text, flags=re.MULTILINE)
            # Xóa số đơn độc ở đầu dòng (như "1." hoặc "123 ") - CHỈ nếu là dòng riêng
            clean_text = re.sub(r"(?m)^\s*\d+[\.:–-]\s*$", "", clean_text)
            # Xóa tất cả ký tự đặc biệt, chỉ giữ chữ cái (bao gồm tiếng Việt), số, khoảng trắng và dấu câu cơ bản
            clean_text = re.sub(r"[^\w\s.,!?();:\"'…—–-]", "", clean_text, flags=re.UNICODE)
            clean_text = re.sub(r"\n{2,}", "\n\n", clean_text).strip()

            all_texts += f"\n\n{clean_text}\n\n"
            time.sleep(delay)

        except Exception as e:
            send_discord_message(f"❌ Lỗi khi tải {chap['name']}: {e}")
            return ""
   
    # 🔹 Ghi cache
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write(all_texts.strip())
    with open(cacheSumary, "w", encoding="utf-8") as f:
        f.write(summary_text.strip())
    return all_texts.strip(),summary_text

def get_novel_text_vivutruyen(url: str, delay: float = 1.0) -> str:
    """
    Cào toàn bộ nội dung truyện từ vivutruyen.net hoặc vivutruyen2.net.
    Nếu miền đầu không có danh sách chương -> thử miền còn lại.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/126.0 Safari/537.36",
        "Referer": "https://google.com/",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    }

    chapters = []
    van_an_text=''
    def fetch_html(u):
        """Return requests.Response or None after a few retries."""
        for _ in range(3):
            try:
                resp = requests.get(u, headers=headers, timeout=15, allow_redirects=True)
                resp.encoding = "utf-8"
                resp.raise_for_status()
                return resp
            except Exception as e:
                send_discord_message(f"⚠️ Lỗi tải {u}: {e}, thử lại...")
                time.sleep(2)
        return None


    from urllib.parse import urljoin, urlparse

    def extract_chapters(soup, page_url: str = ""):
        """Trích xuất danh sách chương từ HTML.
        1) Cấu trúc uk-switcher (vivutruyen)
        2) Fallback cấu trúc grid trong el-content (novatruyen)
        """
        chapterlocal = []

        # 1) uk-switcher tiêu chuẩn
        switcher = soup.select("ul.uk-switcher li div.list")
        if switcher:
            for block in switcher:
                for a in block.select("a.chap-title"):
                    chap_url = a.get("href")
                    chap_name = a.get_text(strip=True)
                    if chap_url and chap_name:
                        # Chuẩn hóa tuyệt đối
                        abs_url = urljoin(page_url, chap_url) if page_url else chap_url
                        chapterlocal.append((chap_name, abs_url))
        else:
            send_discord_message("⚠️ Không tìm thấy danh sách chương trong uk-switcher. Thử fallback el-content...")

            # 2) Fallback: danh sách chương nằm trong el-content của tab (novatruyen)
            # Ví dụ: li.el-item[role="tabpanel"] > div.el-content.uk-panel.uk-margin-top ... a[href]
            containers = [
                "li.el-item[role=tabpanel] div.el-content.uk-panel.uk-margin-top",
                "div.el-content.uk-panel.uk-margin-top",
                "li.el-item .el-content",
                "div.el-content",
                "div.page-children.uk-grid",
            ]

            # Thu thập tất cả container phù hợp (không break sớm để tránh bỏ sót)
            boxes = []
            for sel in containers:
                boxes.extend(soup.select(sel))

            if boxes:
                seen_urls = set()
                for box in boxes:
                    for a in box.select("a[href]"):
                        chap_url = a.get("href")
                        chap_name = a.get_text(" ", strip=True)
                        if not chap_url:
                            continue
                        # Ràng buộc Nova: anchor phải có chữ "chương" trong text để tránh trùng div
                        name_l = (chap_name or "").lower()
                        if "chương" not in name_l and "chuong" not in name_l:
                            continue
                        abs_url = urljoin(page_url, chap_url) if page_url else chap_url
                        if abs_url in seen_urls:
                            continue
                        seen_urls.add(abs_url)
                        chapterlocal.append((chap_name, abs_url))

        return chapterlocal

    def build_domain_variants(u):
        """Tạo danh sách URL tương ứng trên 3 domain: vivutruyen.net, vivutruyen2.net, novatruyen.com.
        Bảo toàn path/slug, đổi host tương ứng. Trả về danh sách unique, giữ thứ tự.
        """
        def replace_host(u0, host):
            m = re.match(r"^(https?://)([^/]+)(/.*)?$", u0)
            if not m:
                return u0
            scheme, _, rest = m.groups()
            rest = rest or "/"
            return f"{scheme}{host}{rest}"

        variants = []
        hosts = ["vivutruyen.net", "vivutruyen2.net", "novatruyen.com"]

        # Nếu URL thuộc host nào thì vẫn thêm bản gốc đầu tiên
        variants.append(u)

        # Thêm các host còn lại, giữ nguyên scheme + path
        for h in hosts:
            if h in u:
                continue
            v = replace_host(u, h)
            if v not in variants:
                variants.append(v)

        # Nếu đầu vào là novatruyen, thêm cả 2 vivu host
        # Nếu đầu vào là vivu, đảm bảo thêm novatruyen
        return variants
    def extract_van_an(soup):
        """Lấy văn án nếu có."""
        # 1) Ưu tiên box chuẩn nếu có
        selectors = [
            "div.uk-card.uk-card-small div.noi-dung",   # box chuẩn
            "div.noi-dung",                              # fallback nhẹ
        ]

        box = None
        for sel in selectors:
            box = soup.select_one(sel)
            if box:
                break

        # 2) Nếu không có box -> lấy từ phần content giới thiệu như ví dụ người dùng đưa
        #   <div class="uk-panel ...">
        #       <h3 class="el-title ...">Giới thiệu truyện ...</h3>
        #       <div class="el-content uk-panel uk-margin-top"> ... <p>...</p> ... </div>
        #   </div>
        if not box:
            box = (
                soup.select_one("div.uk-panel div.el-content.uk-panel.uk-margin-top")
                or soup.select_one("div.el-content.uk-panel.uk-margin-top")
                or soup.select_one("div.uk-panel .el-content")
                or soup.select_one("div.el-content")
            )

        if not box:
            return ""

        parts = []
        for p in box.find_all("p"):
            text = p.get_text(" ", strip=True)
            # Loại bỏ các đoạn chỉ là &nbsp; hoặc rỗng
            if not text or re.fullmatch(r"[\xa0\s]+", text):
                continue
            parts.append(text)

        return "\n\n".join(parts).strip()
    cache_file = os.path.join(CACHE_DIR, f"{url_hash(url)}.txt")
    cacheSumary = os.path.join(CACHE_DIR, f"sumary_{url_hash(url)}.txt")
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                sumary ="";
                send_discord_message(f"📦 Dùng cache: {cache_file}")
                if os.path.exists(cacheSumary):
                    with open(cacheSumary, "r", encoding="utf-8") as s:
                        sumary = s.read().strip()
                       
                           
                return content,sumary
                
    
    # Helper: determine whether fetched page likely corresponds to the requested story/slug.
    def page_matches_requested(orig_url: str, resp: requests.Response, soup: BeautifulSoup) -> bool:
        try:
            orig_path = urlparse(orig_url).path.rstrip('/')
            orig_seg = [s for s in orig_path.split('/') if s]
            orig_slug = orig_seg[-1] if orig_seg else ''
            # If original was a chapter URL like chuong-1, use the parent segment as story slug
            if re.match(r'^(chuong|ch)[-_]?\d+', orig_slug, re.I) and len(orig_seg) >= 2:
                orig_slug = orig_seg[-2]
        except Exception:
            orig_slug = ''

        try:
            final_url = resp.url or ''
            final_path = urlparse(final_url).path.rstrip('/')
            final_seg = [s for s in final_path.split('/') if s]
            final_slug = final_seg[-1] if final_seg else ''
            if re.match(r'^(chuong|ch)[-_]?\d+', final_slug, re.I) and len(final_seg) >= 2:
                final_slug = final_seg[-2]
        except Exception:
            final_slug = ''

        # If we can't determine slugs, be permissive (avoid false positives)
        if not orig_slug or not final_slug:
            return True

        if orig_slug == final_slug:
            return True

        # Check canonical / og:url meta tags for a match to the original slug
        try:
            can = soup.select_one('link[rel=canonical]')
            can_url = can['href'] if can and can.has_attr('href') else ''
        except Exception:
            can_url = ''
        try:
            og = soup.select_one('meta[property="og:url"], meta[name="og:url"]')
            og_url = og['content'] if og and og.has_attr('content') else ''
        except Exception:
            og_url = ''

        if orig_slug and (orig_slug in can_url or orig_slug in og_url):
            return True

        # No strong evidence page matches requested story
        return False

    send_discord_message(f"🌐 Đang tải danh sách chương từ các domain liên quan...")
    for variant in build_domain_variants(url):
        resp = fetch_html(variant)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        # Nếu trang đã redirect sang một truyện khác, bỏ qua biến thể đó
        try:
            if not page_matches_requested(variant, resp, soup):
                send_discord_message(f"⚠️ Có vẻ trang {variant} đã redirect sang truyện khác ({resp.url}), bỏ qua.")
                continue
        except Exception as e:
            # Khi có lỗi trong check, log và tiếp tục bình thường
            send_discord_message(f"⚠️ Lỗi khi kiểm tra redirect cho {variant}: {e}")

        # Lấy văn án nếu chưa có
        if not van_an_text:
            van_an_text = extract_van_an(soup)
        # Gom chương
        cs = extract_chapters(soup, variant)
        if cs:
            chapters.extend(cs)
        else:
            send_discord_message(f"ℹ️ Không tìm thấy chương tại: {variant}")

    if not chapters:
        raise Exception("❌ Không tìm thấy danh sách chương trên cả hai miền.")
    chapters = [c for c in chapters if isinstance(c, (list, tuple)) and len(c) > 0 and c[0]]
    def extract_num(name):
        m = re.search(r"(\d+)", name)
        return int(m.group(1)) if m else 0
   
    # Sắp xếp trước
    chapters.sort(key=lambda c: extract_num(c[0]))

    # Lọc bỏ trùng
    unique = []
    seen = set()

    for c in chapters:
        num = extract_num(c[0])
        if num not in seen:
            unique.append(c)
            seen.add(num)
    chapters = unique
    send_discord_message(f"📚 Tổng số chương tìm thấy: {len(chapters)}")
   
    # Sort theo số chương (vì site thường để ngược)
    


    # Lọc bỏ trùng
  
    all_texts = ''

    for i, chap in enumerate(chapters, start=1):
        try:
          
            chap_resp = fetch_html(chap[1])
            if not chap_resp:
                send_discord_message(f"⚠️ Không tải được chương: {chap[1]}")
                continue
            chap_soup = BeautifulSoup(chap_resp.text, "html.parser")

            # Thử các container phổ biến (thêm cấu trúc trang Nova)
            container = (
                chap_soup.select_one("div.uk-width-1-1.reading")
                or chap_soup.select_one("div.reading-content")
                or chap_soup.select_one("article.uk-article")
                or chap_soup.select_one("div.content-reading")
                or chap_soup.select_one("div.uk-panel.uk-margin-remove-first-child.uk-margin-small.uk-text-justify div.el-content.uk-panel.uk-text-lead")
                or chap_soup.select_one("div.el-content.uk-panel.uk-text-lead")
            )
            if not container:
                raise Exception("❌ Không tìm thấy nội dung truyện trong trang vivutruyen")

            paragraphs = []
            for p in container.find_all("p"):
                # Khôi phục text ẩn trong span.fake
                for fake in p.select("span.fake[data-before]"):
                    real_text = fake.get("data-before", "").strip()
                    fake.replace_with(real_text)

                text = p.get_text(" ", strip=True)
                if not text:
                    continue
                # Lọc quảng cáo, text rác — chỉ loại bỏ những câu chứa pattern, không vứt cả <p>
                try:
                    sentences = re.split(r"(?<=[\.!?。！？])\s+", text)
                except Exception:
                    sentences = [text]

                kept = []
                for s in sentences:
                    if not s:
                        continue
                    # Nếu câu chỉ chứa số -> bỏ
                    if re.fullmatch(r"\s*\d+[\.:\)\-]?\s*", s):
                        continue
                    # Nếu câu bắt đầu bằng số đánh thứ tự (ví dụ "1. ..."), xóa phần đánh số và giữ phần sau
                    s_stripped = re.sub(r"^\s*\d+[\.:\)\-]\s*", "", s)
                    if not s_stripped or not s_stripped.strip():
                        continue
                    s = s_stripped
                    if re.search(r"https?://|nguồn|facebook|novatruyen|\.net|\.com|\.vn", s, re.I):
                        continue
                    kept.append(s.strip())

                if kept:
                    paragraphs.append(" ".join(kept))
                                    
            full_text = "\n\n".join(paragraphs)
            full_text = re.sub(r"\n{2,}", "\n\n", full_text).strip()
            # Xóa "Chương X" ở đầu dòng
            full_text = re.sub(r"(?im)^(chương|chuong)\s*\d+[\.:–-]?\s*", "", full_text, flags=re.MULTILINE)
            # Xóa số đơn độc ở đầu dòng (dòng riêng)
            full_text = re.sub(r"(?m)^\s*\d+[\.\)\-]?\s*$", "", full_text)
            full_text = re.sub(r"\n{2,}", "\n\n", full_text).strip()
            all_texts += full_text + "\n\n"
          
            time.sleep(delay)
        except Exception as e:
            send_discord_message(f"❌ Lỗi khi tải {chap[0]}: {e}")
    
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write(all_texts.strip())
    with open(cacheSumary, "w", encoding="utf-8") as f:
        f.write(van_an_text.strip())

    send_discord_message(f"✅ Hoàn tất, lưu cache: {cache_file}")
    return all_texts.strip(),van_an_text

def get_novel_text_wattpad(url: str, delay: float = 1.0) -> tuple[str, str]:
    """
    Lấy phần mô tả / văn án từ trang Wattpad (nếu có).
    Trả về tuple (full_text, summary_text) — với summary_text là phần "sau chữ Văn án" nếu tìm thấy.
    CHỈ lưu cache summary, KHÔNG lưu cache nội dung truyện (full_text).
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cacheSumary = os.path.join(CACHE_DIR, f"sumary_{url_hash(url)}.txt")

    # Dùng cache summary nếu có
    if os.path.exists(cacheSumary):
        try:
            with open(cacheSumary, "r", encoding="utf-8") as s:
                sumary = s.read().strip()
                send_discord_message(f"📦 Dùng cache summary Wattpad: {cacheSumary}")
                # Trả về rỗng cho full_text vì Wattpad chỉ có summary
                return "", sumary
        except Exception:
            pass

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Referer": "https://google.com/",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.encoding = "utf-8"
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        desc = soup.select_one('div[itemprop="description"]') or soup.select_one('div[itemprop=description]')
        summary_text = ""
        if desc:
            # Lấy toàn bộ text trong div
            desc_text = desc.get_text(" ", strip=True)
            # Tìm vị trí chữ 'văn án' (không phân biệt hoa thường)
            m = re.search(r"văn\s*án", desc_text, re.I)
            if m:
                # Lấy phần sau chữ 'Văn án'
                idx = m.end()
                summary_text = desc_text[idx:].strip(" \n\r\t:–—-–—")
            else:
                # Nếu không thấy cụm 'Văn án', trả nguyên phần mô tả
                summary_text = desc_text.strip()
        else:
            # Fallback: thử meta og:description
            meta = soup.select_one('meta[property="og:description"], meta[name="description"]')
            if meta and meta.has_attr("content"):
                summary_text = meta["content"].strip()

        # Nếu mô tả chứa domain hoặc liên kết (ví dụ: .net, .com, wattpad.net) -> coi như không có văn án
        if summary_text and re.search(r"\.net|\.com|wattpad\.net", summary_text, re.I):
            send_discord_message(f"⚠️ Bỏ qua văn án vì chứa domain trong mô tả: {url}")
            summary_text = ""

    except Exception as e:
        send_discord_message(f"❌ Lỗi khi tải Wattpad {url}: {e}")
        return "", ""

    # Ghi cache CHỈ cho summary (không cache full_text)
    try:
        with open(cacheSumary, "w", encoding="utf-8") as f:
            f.write(summary_text.strip())
    except Exception:
        pass

    return "", summary_text


def extract_first_chapter_link_from_html(html: str, base_url: str | None = None) -> str:
    """
    Từ HTML trang chính truyện, tìm link Chương 1.
    Trả về URL đầy đủ (nếu base_url được cung cấp sẽ dùng urljoin để chuẩn hóa),
    hoặc '' nếu không tìm thấy.
    Chiến lược:
    - Tìm anchor có href chứa '/chuong-1' (case-insensitive)
    - Nếu không tìm thấy, thử các selector phổ biến: .lstbtn a, .findchap a, a span.btn_truyen
    """
    from urllib.parse import urljoin
    soup = BeautifulSoup(html, "html.parser")

    # 1) Tìm anchor href chứa 'chuong-1' hoặc '/chuong-1-'
    a = None
    for cand in soup.find_all('a', href=True):
        href = cand['href']
        if re.search(r"/chuong[-_]?1\b|/chuong-1-", href, re.I):
            a = cand
            break

    # 2) Fallback: tìm .lstbtn a có span.btn_truyen hoặc text 'Chương 1'
    if not a:
        a = soup.select_one("div.lstbtn a[href*='chuong']") or soup.select_one("a:has(span.btn_truyen)")
        if a and not re.search(r"chuong[-_]?1", a.get('href', ''), re.I):
            # kiểm tra text
            txt = a.get_text(" ", strip=True)
            if not re.search(r"chương\s*1|chuong\s*1", txt, re.I):
                a = None

    if not a:
        return ""

    href = a['href']
    if base_url:
        return urljoin(base_url, href)
    # nếu href là absolute thì trả về nguyên vẹn
    if href.startswith('http'):
        return href
    return href


def get_first_chapter_link(url: str, timeout: int = 15) -> str:
    """Tải trang `url` và trả về link chương 1 (chuẩn hóa), hoặc '' nếu không tìm thấy."""
    try:
        resp = requests.get(url, timeout=timeout)
        resp.encoding = 'utf-8'
        resp.raise_for_status()
    except Exception as e:
        send_discord_message(f"❌ Lỗi tải trang chính để tìm chương 1: {e}")
        return ""

    link = extract_first_chapter_link_from_html(resp.text, base_url=resp.url)
    if link:
        send_discord_message(f"ℹ️ Tìm được link Chương 1: {link}")
    else:
        send_discord_message("⚠️ Không tìm thấy link Chương 1 trong trang chính.")
    return link


def extract_chapter_content_and_next(html: str, base_url: str | None = None) -> tuple[str, str]:
    """
    Từ HTML của 1 trang chương, trả về (content_text, next_url).
    - content_text: văn bản trong <div class="truyen"> (chuyển <br> thành \n\n)
    - next_url: link chương tiếp theo (đã chuẩn hóa theo base_url nếu cung cấp) hoặc ''
    """
    from urllib.parse import urljoin
    soup = BeautifulSoup(html, "html.parser")

    content_div = soup.select_one('div.truyen') or soup.select_one('div.reading-content') or soup.select_one('div.content-reading')
    content_text = ""
    if content_div:
        # Thay <br> bằng newline
        for br in content_div.find_all('br'):
            br.replace_with('\n')
        text = content_div.get_text('\n', strip=True)
        # Chuẩn hóa khoảng cách
        content_text = re.sub(r"\n{2,}", "\n\n", text).strip()

    # Tìm link 'Chương tiếp' trong div.chapter_control a.next hoặc a.next
    next_href = ""
    a_next = soup.select_one('div.chapter_control a.next') or soup.select_one('a.next')
    if a_next and a_next.has_attr('href'):
        next_href = a_next['href']
        if base_url:
            next_href = urljoin(base_url, next_href)

    return content_text, next_href


def extract_first_chapter_link_from_html(html: str, base_url: str | None = None) -> str:
    """
    Trích xuất link chương 1 từ đoạn HTML (ví dụ như phần 'link chương 1 nằm ở đây').
    Nếu href là đường dẫn tương đối và base_url được cung cấp, trả về link tuyệt đối.
    Trả về chuỗi rỗng nếu không tìm thấy.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return ""

    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        href = a["href"]
        # Kiểm tra text chứa 'Chương 1' hoặc href chứa 'chuong-1' (không phân biệt hoa thường)
        if re.search(r"chương\s*1", txt, re.I) or re.search(r"chuong[-_]1", href, re.I) or re.search(r"/chuong-1", href, re.I):
            # Chuẩn hóa href
            if href.startswith("//"):
                href = "https:" + href
            if base_url and href.startswith("/"):
                base = re.match(r"https?://[^/]+", base_url)
                if base:
                    href = base.group(0) + href
            elif base_url and not href.startswith("http"):
                href = base_url.rstrip("/") + "/" + href.lstrip("/")
            return href
    return ""


def get_first_chapter_link(page_url: str, timeout: int = 15) -> str:
    """
    Tải trang `page_url` và trả về link tuyệt đối đến chương 1 nếu tìm thấy.
    Sử dụng heuristics: anchor text chứa 'Chương 1' hoặc href chứa '/chuong-1' hoặc 'chuong-1'.
    Trả về chuỗi rỗng nếu không tìm thấy.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Referer": "https://google.com/",
    }
    try:
        resp = requests.get(page_url, headers=headers, timeout=timeout)
        resp.encoding = "utf-8"
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        send_discord_message(f"⚠️ Lỗi khi tải trang để tìm chương 1: {e}")
        return ""

    link = extract_first_chapter_link_from_html(html, base_url=page_url)
    if link:
        return link

    # Fallback: tìm trên toàn bộ các a[href] nếu chưa match
    try:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if re.search(r"/chuong-1|chuong-1|chuong_1|ch-1|ch1", href, re.I):
                if href.startswith("/"):
                    base = re.match(r"https?://[^/]+", page_url)
                    if base:
                        return base.group(0) + href
                elif href.startswith("http"):
                    return href
                else:
                    return page_url.rstrip("/") + "/" + href.lstrip("/")
    except Exception:
        pass

    return ""


def extract_chapter_content_and_next(html: str, base_url: str | None = None) -> tuple[str, str | None]:
    """
    Trích xuất nội dung chương từ HTML và link 'Chương tiếp' nếu có và còn enabled.
    Trả về (content_text, next_link) — next_link = None nếu không tìm thấy hoặc link bị disabled.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return "", None

    # Tìm container nội dung truyện
    container = (
        soup.select_one("div.truyen")
        or soup.select_one("div.reading-content")
        or soup.select_one("div.reading")
        or soup.select_one("article")
    )

    if not container:
        return "", None

    # Lấy văn bản, chuyển <br> thành dòng mới
    content_text = container.get_text("\n\n", strip=True)

    # Tìm nút 'Chương tiếp' và kiểm tra trạng thái
    next_a = None
    # Ưu tiên cấu trúc cụ thể
    nxt = soup.select_one("div.chapter_control a.next")
    if nxt:
        next_a = nxt
    else:
        # Fallback: tìm bất kỳ anchor nào có class 'next' hoặc text 'Chương tiếp'
        for a in soup.find_all("a", href=True):
            cls = a.get("class") or []
            txt = a.get_text(" ", strip=True)
            if "next" in cls or re.search(r"chương\s*tiếp|chương tiếp|next", txt, re.I):
                next_a = a
                break

    if not next_a:
        return content_text, None

    href = next_a.get("href", "").strip()
    cls = next_a.get("class") or []

    # Nếu disabled theo class hoặc href rỗng / javascript / '#', coi như không còn chương tiếp
    if any("disabled" == c or "disabled" in c for c in cls) or not href or href.startswith("javascript") or href == "#":
        return content_text, None

    # Chuẩn hóa thành absolute URL nếu cần
    if href.startswith("//"):
        href = "https:" + href
    if base_url and href.startswith("/"):
        m = re.match(r"https?://[^/]+", base_url)
        if m:
            href = m.group(0) + href
    elif base_url and not href.startswith("http"):
        href = base_url.rstrip("/") + "/" + href.lstrip("/")

    return content_text, href


def crawl_chapters_until_disabled(start_page: str, delay: float = 1.0, max_chapters: int = 500) -> tuple[str, list[str]]:
    """
    Bắt đầu từ một trang truyện (có thể là trang chính hoặc link trực tiếp đến chương 1).
    Nếu start_page là trang chính chứa link tới Chương 1, hàm sẽ tự tìm link đầu tiên.
    Tiếp tục cào các chương theo link 'Chương tiếp' cho đến khi link bị disabled (hoặc không còn).

    Trả về (full_text, chapter_urls) — full_text là chuỗi gộp các nội dung chương, chapter_urls là danh sách các URL đã lấy.
    """
    # Nếu start_page là trang chính (không chứa 'chuong-'), thử tìm link chương 1
    chap_url = start_page
    if not re.search(r"chuong[-_]?\d+", start_page, re.I):
        first = get_first_chapter_link(start_page)
        if first:
            chap_url = first

    collected = []
    urls = []
    count = 0
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Referer": "https://google.com/",
    }

    while chap_url and count < max_chapters:
        try:
            resp = requests.get(chap_url, headers=headers, timeout=20)
            resp.encoding = "utf-8"
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            send_discord_message(f"❌ Lỗi khi tải chương {chap_url}: {e}")
            break

        content, next_link = extract_chapter_content_and_next(html, base_url=chap_url)
        if content:
            # Làm sạch nội dung giống như các method khác
            # Loại bỏ các dòng chứa URL, domain, watermark
            lines = content.split("\n")
            clean_lines = []
            pattern = r"https?://|wattpad|\.net|\.com|\.vn|nguồn|facebook"
            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                # Tách line thành câu và chỉ bỏ những câu chứa pattern
                try:
                    sentences = re.split(r"(?<=[\.!?。！？])\s+", line_stripped)
                except Exception:
                    sentences = [line_stripped]

                kept_sents = []
                for s in sentences:
                    if not s:
                        continue
                    # Nếu câu chỉ chứa số -> bỏ
                    if re.fullmatch(r"\s*\d+[\.:\)\-]?\s*", s):
                        continue
                    # Nếu câu bắt đầu bằng số đánh thứ tự (ví dụ "1. ..."), xóa phần đánh số và giữ phần sau
                    s_stripped = re.sub(r"^\s*\d+[\.:\)\-]\s*", "", s)
                    if not s_stripped or not s_stripped.strip():
                        continue
                    s = s_stripped
                    if re.search(pattern, s, re.I):
                        continue
                    kept_sents.append(s.strip())

                if kept_sents:
                    clean_lines.append(" ".join(kept_sents))

            clean_content = "\n\n".join(clean_lines)
            # Xóa "Chương X" ở đầu dòng
            clean_content = re.sub(r"(?im)^(chương|chuong)\s*\d+[\.:–-]?\s*", "", clean_content, flags=re.MULTILINE)
            # Xóa số đơn độc ở đầu dòng (dòng riêng)
            clean_content = re.sub(r"(?m)^\s*\d+[\.:–-]\s*$", "", clean_content)
            # Xóa tất cả ký tự đặc biệt, chỉ giữ chữ cái (bao gồm tiếng Việt), số, khoảng trắng và dấu câu cơ bản
            clean_content = re.sub(r"[^\w\s.,!?();:\"'…—–-]", "", clean_content, flags=re.UNICODE)
            clean_content = re.sub(r"\n{2,}", "\n\n", clean_content).strip()
            
            if clean_content:
                collected.append(clean_content)
                urls.append(chap_url)
        else:
            send_discord_message(f"⚠️ Không tìm thấy nội dung chương tại {chap_url}")

        count += 1
        if not next_link:
            # Hết chương hoặc bị disabled
            break

        # Nếu next_link giống link hiện tại, coi như đã hết chương (tránh vòng lặp)
        if next_link == chap_url:
            break

        chap_url = next_link
        time.sleep(delay)

    full = "\n\n".join(collected).strip()
    return full, urls


def get_wattpad_novel(url: str, delay: float = 1.0, max_chapters: int = 500) -> tuple[str, str, list[str]]:
    """
    Tích hợp: lấy văn án từ trang Wattpad và cào lần lượt các chương theo 'Chương tiếp'
    cho đến khi link 'Chương tiếp' bị disabled.

    Trả về (full_text, summary_text, chapter_urls)
    - full_text: CHỈ nội dung các chương (KHÔNG bao gồm văn án)
    - summary_text: phần tóm tắt / văn án thuần (không kèm header)
    - chapter_urls: danh sách URL chương đã cào (theo thứ tự)
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, f"{url_hash(url)}.txt")
    cacheSumary = os.path.join(CACHE_DIR, f"sumary_{url_hash(url)}.txt")

    # 🔹 Dùng cache nếu có
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                sumary = ""
                send_discord_message(f"📦 Dùng cache Wattpad: {cache_file}")
                if os.path.exists(cacheSumary):
                    with open(cacheSumary, "r", encoding="utf-8") as s:
                        sumary = s.read().strip()
                # Không trả chapter_urls từ cache, chỉ trả nội dung
                return content, sumary, []

    try:
        # Lấy văn án (summary)
        _, summary_text = get_novel_text_wattpad(url, delay=delay)

        # Tìm link chương 1 (có thể trên trang chính hoặc đã có trong URL)
        first = get_first_chapter_link(url)
        if not first:
            send_discord_message(f"⚠️ Không tìm thấy link Chương 1 cho: {url}")
            # Trả về chỉ văn án nếu có
            return "", summary_text, []

        # Cào các chương từ chương 1 đến khi 'next' disabled
        chapters_text, chapter_urls = crawl_chapters_until_disabled(first, delay=delay, max_chapters=max_chapters)

        # Chỉ trả nội dung chương, không nối văn án
        full = chapters_text

        # 🔹 Ghi cache
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(full.strip())
        with open(cacheSumary, "w", encoding="utf-8") as f:
            f.write(summary_text.strip())

        send_discord_message(f"✅ Hoàn tất Wattpad, lưu cache: {cache_file}")
        return full.strip(), summary_text, chapter_urls
    except Exception as e:
        send_discord_message(f"❌ Lỗi get_wattpad_novel: {e}")
        return "", "", []


def extract_domain_structure(url): 
    """Tự nhận biết domain và chọn cấu trúc phù hợp""" 
    domain = re.search(r"https?://([^/]+)/", url).group(1) 
    if "metruyenhot" in domain: 
        return {"content_selector": "div.chapter-c", "next_text": "Tiếp"} 
    elif "truyenfull" in domain: 
        return {"content_selector": "div.chapter-c", "next_text": "Chương tiếp"} 
    else: return {"content_selector": "div.chapter", "next_text": "Next"}


def get_novel_text_wattpad_com(url: str, delay: float = 1.0, max_chapters: int = 500) -> tuple[str, str]:
    """
    Xử lý riêng cho domain wattpad.com (khác với wattpad.com.vn).
    Chiến lược:
    - Lấy summary bằng `get_novel_text_wattpad` (nó chỉ trả summary cho trang Wattpad nếu có).
    - Tìm link Chương 1 bằng `get_first_chapter_link`. Nếu không có, thử biến thể mobile (m.wattpad.com).
    - Dùng `crawl_chapters_until_disabled` để lần lượt lấy chương với user-agent mobile.
    - Ghi cache tương tự các hàm khác.
    Trả về (full_text, summary_text)
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, f"{url_hash(url)}.txt")
    cacheSumary = os.path.join(CACHE_DIR, f"sumary_{url_hash(url)}.txt")

    # Dùng cache nếu có
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    sumary = ""
                    send_discord_message(f"📦 Dùng cache Wattpad(.com): {cache_file}")
                    if os.path.exists(cacheSumary):
                        with open(cacheSumary, "r", encoding="utf-8") as s:
                            sumary = s.read().strip()
                    return content, sumary
        except Exception:
            pass

    # wattpad.com: không cần summary, chỉ lấy nội dung chương
    summary_text = ""

    # Tìm link chương 1
    first = url
    # Nếu không tìm thấy, thử biến thể mobile
    if not first:
        try:
            # chuyển host sang m.wattpad.com
            first_candidate = re.sub(r"https?://(www\.)?wattpad\.com", "https://m.wattpad.com", url)
            first = get_first_chapter_link(first_candidate)
        except Exception:
            first = ""

    if not first:
        send_discord_message(f"⚠️ Không tìm thấy link Chương 1 cho (wattpad.com): {url}")
        # Trả về chỉ summary nếu có
        return "", (summary_text or "")

    # Crawl chương cho wattpad.com — sử dụng container đặc thù
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
        "Referer": "https://google.com/",
    }

    collected = []
    urls = []
    chap_url = first
    # Normalize helper for URL comparisons (ignore trailing slash and lowercase host)
    from urllib.parse import urlparse, urljoin
    def _norm(u: str) -> str:
        try:
            p = urlparse(u)
            scheme = p.scheme or 'https'
            netloc = (p.netloc or '').lower()
            path = p.path or '/'
            # remove trailing slash for comparison
            path = path.rstrip('/')
            return f"{scheme}://{netloc}{path}"
        except Exception:
            return (u or '').rstrip('/').lower()

    norm_first = _norm(first)
    count = 0

    while chap_url and count < max_chapters:
        try:
            resp = requests.get(chap_url, headers=headers, timeout=20)
            resp.encoding = 'utf-8'
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
        except Exception as e:
            send_discord_message(f"⚠️ Lỗi tải chương Wattpad(.com) {chap_url}: {e}")
            break

        # Tìm container theo selector mà bạn cung cấp
        container = soup.select_one("div.panel.panel-reading") or soup.select_one("div.panel-reading") or soup.select_one("div[dir=\"ltr\"]")
        chapter_text = ""
        if container:
            # ưu tiên lấy <pre> nếu có
            pref = container.select_one('pre') or container

            # Loại bỏ các widget/komponent không cần thiết
            for bad in pref.select('div.component-wrapper, button, .trinityAudioPlaceholder'):
                bad.decompose()

            # Thay <br> bằng newline
            for br in pref.find_all('br'):
                br.replace_with('\n')

            paras = []
            for p in pref.find_all('p'):
                text = p.get_text(' ', strip=True)
                if not text:
                    continue
                # Lọc rác: chỉ loại bỏ những câu/đoạn nhỏ chứa URL/domain/wattpad,
                # không vứt cả thẻ <p> khi chỉ một phần là quảng cáo.
                # Tách paragraph thành câu (đơn giản bằng regex) và giữ lại các câu không chứa pattern.
                try:
                    sentences = re.split(r"(?<=[\.!?。！？])\s+", text)
                except Exception:
                    sentences = [text]

                kept = []
                for s in sentences:
                    if not s:
                        continue
                    # Nếu câu chỉ chứa số -> bỏ
                    if re.fullmatch(r"\s*\d+[\.:\)\-]?\s*", s):
                        continue
                    # Nếu câu bắt đầu bằng số đánh thứ tự (ví dụ "1. ..."), xóa phần đánh số và giữ phần sau
                    s_stripped = re.sub(r"^\s*\d+[\.:\)\-]\s*", "", s)
                    if not s_stripped or not s_stripped.strip():
                        continue
                    s = s_stripped
                    if re.search(r"https?://|wattpad|nguồn|facebook|\.com", s, re.I):
                        # chỉ bỏ câu này
                        continue
                    kept.append(s.strip())

                if kept:
                    paras.append(" ".join(kept))

            if not paras:
                # fallback: lấy toàn bộ text trong pre/container
                chapter_text = re.sub(r"\n{2,}", "\n\n", pref.get_text('\n', strip=True)).strip()
            else:
                chapter_text = "\n\n".join(paras).strip()
        else:
            send_discord_message(f"⚠️ Không tìm thấy container đọc của Wattpad tại: {chap_url}")

        if chapter_text:
            collected.append(chapter_text)
            urls.append(chap_url)

        # Tìm link chương tiếp theo trong trang Wattpad
        next_link = None
        # 1) specific navigation container often used on Wattpad
        nav_a = soup.select_one('#story-part-navigation a') or soup.select_one('div.story-part-navigation a')
        if nav_a and nav_a.has_attr('href'):
            next_link = nav_a['href']
       

        # Normalize next_link
        if next_link:
            if next_link.startswith('//'):
                next_link = 'https:' + next_link
            if not next_link.startswith('http'):
                try:
                    next_link = urljoin(chap_url, next_link)
                except Exception:
                    next_link = chap_url.rstrip('/') + '/' + next_link.lstrip('/')

        # advance
        if not next_link:
            break

        # If next_link equals current chap_url or equals the initial first chapter, treat as end
        if next_link == chap_url or _norm(next_link) == norm_first:
            break
        chap_url = next_link
        count += 1
        time.sleep(delay)

    full_text = '\n\n'.join(collected).strip()

    # Ghi cache (chỉ nội dung) — không lưu summary cho wattpad.com
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            f.write(full_text)
    except Exception:
        pass

    send_discord_message(f"✅ Hoàn tất Wattpad(.com), lưu cache: {cache_file}")
    return full_text, (summary_text or "")

def get_novel_text(url: str, include_summary: bool = True) -> tuple[str, str]:
    """
    Lấy toàn bộ nội dung truyện (MetruyenHot, TruyenFull, v.v.)
    - MetruyenHot: hỗ trợ cả <p> text thường và <p> có text trong attribute lạ
    - Tự loại watermark
    - Dùng cache
    Trả về: (full_text, summary_text) - full_text CHỈ chứa nội dung truyện, KHÔNG có văn án
    """
    info = extract_domain_structure(url)
    base_url = re.match(r"https?://[^/]+", url).group(0)
    cache_file = os.path.join(CACHE_DIR, f"{url_hash(url)}.txt")
    cacheSumary = os.path.join(CACHE_DIR, f"sumary_{url_hash(url)}.txt")

    # Dùng cache nếu có
    if os.path.exists(cache_file):
        send_discord_message("📦 Dùng cache truyện từ %s", cache_file)
        with open(cache_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                # Đọc cache văn án nếu có (chỉ khi caller yêu cầu)
                sumary = ""
                if include_summary and os.path.exists(cacheSumary):
                    try:
                        with open(cacheSumary, "r", encoding="utf-8") as s:
                            sumary = s.read().strip()
                    except Exception:
                        sumary = ""
                return content, (sumary if include_summary else "")
            else:
                send_discord_message("⚠️ File cache rỗng, tải lại nội dung...")

    all_text = ""
    summary_text = ""
    # Nếu là TruyenFull: lấy văn án từ trang chính (loại bỏ /chuong-1/)
    try:
        domain_check = re.search(r"https?://([^/]+)/", url).group(1)
    except Exception:
        domain_check = ""

    if "truyenfull" in domain_check:
        try:
            main_url = re.sub(r"/chuong-\d+/?$", "/", url)
            if main_url == url and not main_url.endswith('/'):
                # vẫn thử thêm '/' để chắc chắn
                main_url = url + "/"
            send_discord_message("🔎 Lấy văn án từ trang chính: %s", main_url)
            resp_main = requests.get(main_url, timeout=15)
            resp_main.encoding = "utf-8"
            soup_main = BeautifulSoup(resp_main.text, "lxml")
            desc = soup_main.select_one('div.desc-text.desc-text-full[itemprop="description"]') \
                   or soup_main.select_one('div.desc-text[itemprop="description"]') \
                   or soup_main.select_one('div.desc-text')

            if desc and include_summary:
                paras = []
                for p in desc.find_all(['p','div']):
                    t = p.get_text(" ", strip=True)
                    if not t or re.fullmatch(r"[\xa0\s]+", t):
                        continue
                    paras.append(t)
                summary_text = "\n\n".join(paras).strip()
        except Exception as e:
            send_discord_message("⚠️ Không lấy được văn án TruyenFull: %s", e)
    chapter = 1

    while url:
      
        try:
            response = requests.get(url, timeout=15)
            response.encoding = "utf-8"
        except Exception as e:
            send_discord_message("❌ Lỗi tải trang %s: %s", url, e)
            break

        soup = BeautifulSoup(response.text, "lxml")

        # === Xóa watermark & script ===
        for wm in soup.select("div.show-c, div.ads, script, style"):
            wm.decompose()

        domain = re.search(r"https?://([^/]+)/", url).group(1)
        clean_text = ""

        # === MetruyenHot ===
        if "metruyenhot" in domain:
            container = soup.select_one("div.book-list.full-story.content.chapter-c")
            if not container:
                send_discord_message("❌ Không tìm thấy nội dung truyện trong MetruyenHot")
                break

            paragraphs = []
            default_attrs = {"class", "style", "onmousedown", "onselectstart", "oncopy", "oncut"}

            for p in container.find_all("p"):
                text_content = ""

                # Nếu <p> có text trực tiếp
                if p.get_text(strip=True):
                    text_content = p.get_text(" ", strip=True)
                else:
                    # Nếu text nằm trong attribute lạ
                    for attr, val in p.attrs.items():
                        if attr not in default_attrs and isinstance(val, str) and val.strip():
                            text_content = val.strip()
                            break

                # Bỏ watermark hoặc dòng rác
                if text_content and not re.search(r"metruyen\s*hot", text_content, re.I):
                    paragraphs.append(text_content)

            clean_text = "\n\n".join(paragraphs)
        elif "laophatgia" in domain:
            return get_novel_text_laophatgia(url)
        elif "wattpad" in domain:
            # Distinguish between wattpad.com (use dedicated handler) and other Wattpad domains (e.g., wattpad.com.vn)
            try:
                if "wattpad.com" in domain:
                    full_text, summary_text = get_novel_text_wattpad_com(url, delay=1.0)
                    return full_text, summary_text
                else:
                    full_text, summary_text, _ = get_wattpad_novel(url, delay=1.0)
                    return full_text, summary_text
            except Exception as e:
                send_discord_message(f"⚠️ Lỗi khi xử lý Wattpad cho domain {domain}: {e}")
                return "", ""
        elif "vivutruyen" in domain or "vivutruyen2" in domain:

            return get_novel_text_vivutruyen(url)
        # === TruyenFull hoặc site khác ===
        elif "truyenfull" in domain:
            content = soup.select_one(info["content_selector"])
            if not content:
                send_discord_message("❌ Không tìm thấy nội dung tại %s", url)
                break

            # Xóa các watermark hoặc phần quảng cáo
            for wm in content.select("div.show-c, div.ads, script, style"):
                wm.decompose()

            clean_text = content.get_text("\n", strip=True)

    # === Làm sạch nội dung ===
        # Xóa "Chương X" ở đầu dòng
        clean_text = re.sub(r"(?im)^(chương|chuong)\s*\d+[\.:–-]?\s*", "", clean_text, flags=re.MULTILINE)
        # Xóa số đơn độc ở đầu dòng (dòng riêng)
        clean_text = re.sub(r"(?m)^\s*\d+[\.:–-]\s*$", "", clean_text)
        clean_text = re.sub(r"\n{2,}", "\n\n", clean_text).strip()

        all_text += clean_text + "\n\n"

        # === Xác định link chương tiếp theo ===
        next_url = None
        if "truyenfull" in domain:
            next_link = soup.find("a", id="next_chap")
            if next_link and next_link.get("href"):
                next_url = next_link["href"]
        elif "metruyenhot" in domain:
            next_link = soup.find("a", attrs={"rel": "next"}) or \
                        soup.find("a", string=re.compile("Tiếp", re.I))
            if next_link and next_link.get("href"):
                next_url = next_link["href"]

        # Fallback chung
        if not next_url:
            for a in soup.select("a"):
                href = a.get("href")
                if href and re.search(r"(chương\s*tiếp|tiếp|next)", a.get_text(strip=True), re.I):
                    next_url = href
                    break

        # Chuẩn hóa URL
        if next_url and not next_url.startswith("javascript"):
            norm_next = next_url if next_url.startswith("http") else base_url + next_url
            # Nếu next giống URL hiện tại -> xem như chương cuối
            if norm_next == url:
                send_discord_message("🚪 Hết chương tại: %s", url)
                url = None
            else:
                url = norm_next
                chapter += 1
        else:
            send_discord_message("🚪 Hết chương tại: %s", url)
            url = None
        # === Ghi cache từng chương (overwrite) === 
    with open(cache_file, "w", encoding="utf-8") as f: 
        f.write(all_text) 
    # Ghi cache summary (nếu có và caller cho phép)
    try:
        if include_summary:
            with open(cacheSumary, "w", encoding="utf-8") as s:
                s.write(summary_text or "")
    except Exception:
        pass

    return all_text.strip(), (summary_text if include_summary else "")



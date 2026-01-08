# 🎬 HƯỚNG DẪN SỬ DỤNG ENDPOINT: STORY TO VIDEO

## 📋 Tổng Quan

Endpoint `/generate_story_to_video` tự động hóa hoàn toàn quy trình từ tạo truyện đến video:

1. **Tạo truyện** bằng AI (3 thể loại)
2. **Chuyển văn bản → Audio** (OpenAI TTS)
3. **Xử lý audio** (tăng tốc + nhạc nền)
4. **Render video** (audio + background videos)
5. **Upload lên Drive** (tự động)

**Thời gian ước tính:** 10-30 phút/video (tùy độ dài truyện)

---

## 🎭 3 Thể Loại Truyện

### 1. 👻 KINH DỊ (Horror)
**Đặc điểm:**
- Phong cách: Ma mị, u ám, huyền bí Việt Nam
- Độ dài: ~10,000 từ (10 chương)
- Nhiệt độ AI: 0.8 (cân bằng)
- Chi phí: ~$0.02-0.60/truyện (tùy model)

**Ví dụ chủ đề:**
- Làng cổ có lời nguyền "không ai được gọi tên người chết"
- Bệnh viện bỏ hoang – nơi một y tá vẫn làm việc mỗi đêm
- Trường học xây trên nền nghĩa địa

### 2. 💥 VẢ MẶT (Face Slap)
**Đặc điểm:**
- Phong cách: Giả nghèo phản đòn, drama sảng khoái
- Độ dài: ~10,000 từ (10 chương)
- Nhiệt độ AI: 0.85 (sáng tạo)
- Cấu trúc: Bị coi thường → Bóc phốt → Vả mặt → Kết thúc đắng lòng

**Ví dụ vai giả nghèo:**
- Chủ tịch tập đoàn → Giả làm nhân viên tạp vụ
- Thiên tài y học → Giả làm bác sĩ tập sự
- Tổng tài IT → Giả làm thực tập sinh

### 3. 🎲 RANDOM MIX (Ngẫu Nhiên)
**Đặc điểm:**
- Phong cách: Kết hợp ngẫu nhiên nhiều thể loại
- Độ dài: ~10,000 từ (10 chương)
- Nhiệt độ AI: 0.9 (cực sáng tạo)
- Tổ hợp: 10×10×10×10×6 = 600,000 khả năng

**5 yếu tố ngẫu nhiên:**
1. Thể loại chính (10 lựa chọn)
2. Thể loại phụ (10 lựa chọn)
3. Nhân vật (10 lựa chọn)
4. Bối cảnh (10 lựa chọn)
5. Motif cốt truyện (6 lựa chọn)

---

## 🔌 API Endpoint

### URL
```
POST http://localhost:8000/generate_story_to_video
```

### Parameters

#### Bắt buộc:
- `genre`: Thể loại (`"horror"`, `"face_slap"`, `"random_mix"`)
- `video_urls`: URL video background (phân cách bằng dấu phẩy)

#### Tùy chọn chung:
- `title`: Tiêu đề video (để trống = dùng tiêu đề truyện tự động) ✅
- `model`: Model AI (`"gpt-4o-mini"`, `"gpt-4o"`, `"gpt-4-turbo"`)
- `voice_style`: Style đọc audio
- `bg_choice`: Tên file nhạc nền
- `part_duration`: Thời lượng mỗi part (giây, mặc định 3600)

#### Horror cụ thể:
- `horror_theme`: Chủ đề kinh dị
- `horror_setting`: Bối cảnh

#### Face Slap cụ thể:
- `face_slap_theme`: Chủ đề vả mặt
- `face_slap_role`: Vai giả nghèo
- `face_slap_setting`: Bối cảnh

#### Random Mix cụ thể:
- `random_main_genre`: Thể loại chính
- `random_sub_genre`: Thể loại phụ
- `random_character`: Nhân vật
- `random_setting`: Bối cảnh
- `random_plot_motif`: Motif cốt truyện

---

## 💻 Ví Dụ Sử Dụng

### 1. Python (requests)

```python
import requests

# Horror Story
response = requests.post(
    "http://localhost:8000/generate_story_to_video",
    params={
        "genre": "horror",
        "video_urls": "https://youtube.com/shorts/abc,https://youtube.com/shorts/xyz",
        "model": "gpt-4o-mini",
        "horror_theme": "Làng cổ có lời nguyền",
        "horror_setting": "làng quê xa xôi miền Bắc"
    }
)

task_id = response.json()["task_id"]
print(f"Task ID: {task_id}")

# Theo dõi tiến trình
status = requests.get(
    "http://localhost:8000/task_status",
    params={"task_id": task_id}
)
print(status.json())
```

### 2. cURL

```bash
# Face Slap Story
curl -X POST "http://localhost:8000/generate_story_to_video" \
  -d "genre=face_slap" \
  -d "video_urls=https://youtube.com/shorts/abc" \
  -d "model=gpt-4o-mini" \
  -d "face_slap_role=Chủ tịch tập đoàn"

# Random Mix Story
curl -X POST "http://localhost:8000/generate_story_to_video" \
  -d "genre=random_mix" \
  -d "video_urls=https://youtube.com/shorts/abc" \
  -d "model=gpt-4o"
```

### 3. JavaScript (Fetch)

```javascript
const response = await fetch('http://localhost:8000/generate_story_to_video', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({
    genre: 'horror',
    video_urls: 'https://youtube.com/shorts/abc',
    model: 'gpt-4o-mini'
  })
});

const { task_id } = await response.json();
console.log('Task ID:', task_id);
```

---

## 🤖 Discord Bot Commands

### Command: `/story_to_video`

**Mô tả:** Tạo truyện → audio → video với 3 lựa chọn thể loại

**Cách dùng:**
1. Gõ `/story_to_video` trong Discord
2. Chọn nhạc nền (tùy chọn)
3. Chọn 1 trong 3 nút:
   - 👻 **Kinh Dị**
   - 💥 **Vả Mặt**
   - 🎲 **Random Mix**
4. Điền form (tất cả đều tự động lấy tiêu đề từ truyện)
5. Nhận Task ID để theo dõi

### Command: `/task_status`

**Mô tả:** Kiểm tra tiến trình task

**Cách dùng:**
```
/task_status task_id: 20241111-123456-789012
```

**Output:**
- Progress bar (0-100%)
- Phase hiện tại (generating_story, generating_audio, rendering_video, ...)
- Video files (khi hoàn tất)
- Story path, Audio path

---

## 📊 Tracking Progress

### Các Phase:
1. **initializing** (0-5%) - Khởi tạo
2. **generating_story** (5-15%) - Tạo truyện bằng AI
3. **generating_audio** (15-40%) - Chuyển văn bản → audio
4. **processing_audio** (40-50%) - Xử lý audio (tăng tốc + nhạc nền)
5. **rendering_video** (50-95%) - Render video
6. **completed** (100%) - Hoàn tất

### Status:
- `pending`: Đang chờ trong queue
- `running`: Đang xử lý
- `completed`: Hoàn tất
- `error`: Lỗi

---

## 💰 Chi Phí Ước Tính

### Model: gpt-4o-mini (khuyên dùng)
- Chi phí: ~$0.02/truyện
- Tốc độ: Nhanh
- Chất lượng: Tốt

### Model: gpt-4o
- Chi phí: ~$0.52/truyện
- Tốc độ: Trung bình
- Chất lượng: Xuất sắc (khuyên dùng cho Random Mix)

### Model: gpt-4-turbo
- Chi phí: ~$0.60/truyện
- Tốc độ: Trung bình
- Chất lượng: Xuất sắc

**Lưu ý:** Chi phí TTS (audio) khoảng $15-30/1 triệu ký tự (~$0.15-0.30/truyện)

---

## ⚠️ Lưu Ý Quan Trọng

### 1. Tiêu đề video
- **KHÔNG CẦN** nhập tiêu đề trong form
- Hệ thống tự động lấy tiêu đề từ truyện đã tạo
- Tiêu đề sẽ được trích xuất từ tên file truyện

### 2. Video background
- Cần ít nhất 1 URL video
- Có thể nhập nhiều URL (phân cách bằng dấu phẩy)
- Hệ thống sẽ tự động tải và xử lý

### 3. Thời gian xử lý
- Tạo truyện: 2-5 phút
- Tạo audio: 5-10 phút
- Render video: 3-15 phút
- **Tổng:** 10-30 phút

### 4. Dung lượng
- File truyện: ~20-50 KB
- File audio: 50-150 MB
- File video: 200-500 MB/part

---

## 🐛 Troubleshooting

### Task bị lỗi
```bash
# Kiểm tra logs
curl http://localhost:8000/task_status?task_id=<TASK_ID>
```

### Video không có tiêu đề
- ✅ Bình thường! Tiêu đề được thêm tự động khi render
- Kiểm tra `final_title` trong task info

### Audio quá nhanh/chậm
- Chỉnh `voice_style` parameter
- Mặc định: tốc độ 1.45x

### Hết API key
- Kiểm tra `key.json` (cho FPT TTS - deprecated)
- Hoặc OpenAI API key trong `openai.api_key`

---

## 📁 Output Files

### Cấu trúc file:
```
outputs/
├── YYYYMMDD_HHMMSS_<title>.txt          # File truyện gốc
├── <slug>.flac                           # Audio gốc
├── <slug>_capcut.flac                    # Audio đã xử lý
├── <slug>_bg_1.mp4                       # Video background 1
├── <slug>_bg_2.mp4                       # Video background 2
├── <slug>_final.mp4                      # Video chính (full)
├── <slug>_final_part_1.mp4              # Part 1 (nếu > 1h)
└── <slug>_final_part_2.mp4              # Part 2

stories/
└── YYYYMMDD_HHMMSS_<title>.txt          # Backup truyện
```

---

## 🔗 API Endpoints Liên Quan

- `/generate_story_to_video` - Tạo full pipeline
- `/task_status?task_id=<ID>` - Kiểm tra tiến trình
- `/tasks` - Liệt kê tất cả tasks
- `/download_video?task_id=<ID>` - Tải video
- `/maintenance/trim_storage` - Dọn dẹp cache

---

## 📞 Support

- Kiểm tra log: Check Discord notifications
- API docs: `http://localhost:8000/docs`
- Test script: `python test_story_to_video_endpoint.py`

---

**Tạo bởi:** Story Generator + FastAPI + OpenAI TTS  
**Version:** 1.0  
**Updated:** 2024-11-11

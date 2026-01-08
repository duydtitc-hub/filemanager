# 🚀 Quick Start - Story Generator

## ⚡ Tạo Truyện Trong 30 Giây

```python
from story_generator import create_horror_story

result = create_horror_story(model="gpt-4o")
print(result['content'])
```

**Output**: Truyện kinh dị 10.000 từ, tự động lưu trong `stories/`

---

## 🎯 Chọn Model Nào?

```python
# 💰 Rẻ nhất (~$0.01/truyện)
create_horror_story(model="gpt-4o-mini")

# ⚖️ Cân bằng (~$0.26/truyện)  ← KHUYẾN NGHỊ
create_horror_story(model="gpt-4o")

# 🌟 Tốt nhất (~$0.51/truyện)
create_horror_story(model="gpt-4-turbo")
```

---

## 📚 Chọn Chủ Đề

```python
from story_generator import StoryPrompts

# Xem tất cả chủ đề
for theme in StoryPrompts.KINH_DI['themes']:
    print(theme)

# Tạo với chủ đề cụ thể
result = create_horror_story(
    theme='Bệnh viện bỏ hoang – nơi một y tá vẫn làm việc mỗi đêm.',
    model="gpt-4o"
)
```

---

## 🛠️ Tùy Chỉnh

```python
result = create_horror_story(
    theme="...",
    setting="làng quê xa xôi miền Bắc",
    model="gpt-4o",
    temperature=0.85,  # 0.0-1.0 (cao = sáng tạo hơn)
    custom_requirements="""
    - Nhân vật chính là nhà báo
    - Có yếu tố công nghệ hiện đại
    - Kết thúc mở
    """
)
```

---

## 📊 Xem Kết Quả

```python
print(f"Tiêu đề: {result['title']}")
print(f"Số từ: {result['word_count']:,}")
print(f"File: {result['file_path']}")

# Xem các chương
for ch in result['metadata']['chapters']:
    print(f"{ch['name']}: {ch['word_count']} từ")
```

---

## 🔥 Các Lệnh Nhanh

```bash
# Demo đơn giản
python demo_create_story.py

# Test đầy đủ
python test_story_generator.py

# So sánh models
python test_models.py

# Tạo trực tiếp
python story_generator.py
```

---

## ⚠️ Lỗi Thường Gặp

### "context_length_exceeded"
```python
# ❌ KHÔNG dùng
StoryGenerator(model="gpt-4")  # Context nhỏ!

# ✅ DÙNG
StoryGenerator(model="gpt-4o")  # Context lớn
```

### "Invalid API key"
→ Sửa API key trong `story_generator.py` dòng 13

### Truyện quá ngắn
→ Tăng temperature hoặc thêm yêu cầu cụ thể

---

## 💰 Chi Phí Ước Tính

| Số truyện | gpt-4o-mini | gpt-4o | gpt-4-turbo |
|-----------|-------------|--------|-------------|
| 1 truyện | $0.01 | $0.26 | $0.51 |
| 10 truyện | $0.10 | $2.60 | $5.10 |
| 100 truyện | $1.00 | $26.00 | $51.00 |

---

## 📖 Đọc Thêm

- `README_STORY_GENERATOR.md` - Hướng dẫn đầy đủ
- `MODEL_GUIDE.md` - Chi tiết về models
- `CHANGELOG_STORY_GENERATOR.md` - Lịch sử thay đổi

---

**Chúc bạn viết truyện vui vẻ! 🎃**

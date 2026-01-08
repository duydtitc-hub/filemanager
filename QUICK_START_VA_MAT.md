# 🎉 CẬP NHẬT: ĐÃ THÊM THỂ LOẠI VẢ MẶT

## ✨ Thông báo

Hệ thống tạo truyện đã được cập nhật thêm thể loại mới:

### 🎭 VẢ MẶT - FACE SLAP

Thể loại truyện đô thị hiện đại, hài hước với concept:
- Nhân vật giàu/có địa vị giả làm người bình thường
- Bị coi thường vì vẻ ngoài giản dị
- Cuối cùng lộ thân phận → "vả mặt" cực hả hê
- Thông điệp: "Đừng đánh giá người qua bề ngoài"

## 🚀 Sử dụng ngay

### Tạo truyện VẢ MẶT

```bash
# Demo nhanh (ngẫu nhiên)
python demo_create_face_slap.py

# Hoặc chọn lựa chi tiết
python test_face_slap_generator.py
```

### Tạo truyện KINH DỊ (như trước)

```bash
# Demo nhanh
python demo_create_story.py

# Hoặc chọn lựa chi tiết  
python test_story_generator.py
```

## 📚 Tài liệu

- **Hướng dẫn Vả Mặt**: `GUIDE_FACE_SLAP.md`
- **Changelog**: `CHANGELOG_VA_MAT.md`
- **README gốc**: `README_STORY_GENERATOR.md`

## 💻 Code Example

```python
from story_generator import StoryGenerator

generator = StoryGenerator(model="gpt-4o-mini")

# Tạo truyện vả mặt
result = generator.generate_face_slap_story()

print(f"✅ {result['title']}")
print(f"📝 {result['word_count']:,} từ")
print(f"💾 {result['file_path']}")
```

## 🎯 2 Thể loại hiện có

| Thể loại | Function | Phong cách | Khuyến nghị |
|----------|----------|-----------|-------------|
| 👻 Kinh Dị | `generate_horror_story()` | Ma mị, u ám, ám ảnh | Audio truyện đêm khuya |
| 🎭 Vả Mặt | `generate_face_slap_story()` | Hài hước, hả hê, hiện đại | Audio truyện giải trí |

## ⚙️ Model AI

- **gpt-4o-mini**: ~$0.02/truyện (test, demo)
- **gpt-4o**: ~$0.52/truyện (production) ⭐
- **gpt-4-turbo**: ~$0.60/truyện (cao cấp)

## 📁 Files mới

```
demo_create_face_slap.py       # Demo tạo vả mặt
test_face_slap_generator.py    # Test tương tác vả mặt
GUIDE_FACE_SLAP.md            # Hướng dẫn chi tiết
CHANGELOG_VA_MAT.md           # Changelog
```

## 🎨 Đặc điểm Vả Mặt

### Cấu trúc (10 chương)
1. Giới thiệu thân phận giả
2. Bị coi thường
3. Tình huống "tấu hài"
4. Phản đòn tinh tế
5. Gợi mở thân phận thật
6. Sự kiện quan trọng
7. Sắp lộ diện
8. **VẢ MẶT** đỉnh cao
9. Hậu quả, xin lỗi
10. Kết thúc ý nghĩa

### Phong cách
- **Ngôi kể**: Thứ nhất ("tôi")
- **Hội thoại**: Nhiều, sống động
- **Tiết tấu**: Nhanh, vui nhộn
- **Kết thúc**: Hả hê, văn minh

### 10 Chủ đề

1. Shipper → Chủ tịch công ty
2. Thực tập sinh → Nhà đầu tư lớn nhất
3. Cô gái giản dị → Người thừa kế
4. Freelancer → Chủ nền tảng
5. Học sinh nghèo → Con ông chủ trường
6. Nhân viên tạp vụ → CEO ẩn danh
7. Bảo vệ → Chủ tòa nhà
8. Phục vụ cafe → Chủ chuỗi cafe
9. Sinh viên dạy kèm → Giáo sư trẻ nhất
10. Tài xế taxi → Ông chủ hãng xe

## 🔥 Thử ngay!

```bash
python demo_create_face_slap.py
```

Truyện sẽ được lưu tại `stories/YYYYMMDD_HHMMSS_vamat_<title>.txt`

---

**Chúc bạn tạo được nhiều truyện hay! 🎉**

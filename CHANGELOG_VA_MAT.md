# CHANGELOG - Thêm thể loại VẢ MẶT

## 📅 Ngày cập nhật: 2025-11-11

## ✨ Tính năng mới

### 🎭 Thêm thể loại "VẢ MẶT - FACE SLAP"

Thể loại truyện đô thị hiện đại, hài hước với concept:
- Nhân vật giàu/có địa vị giả làm người bình thường
- Bị coi thường vì vẻ ngoài
- Cuối cùng lộ thân phận → "vả mặt" hả hê

## 📝 Files đã thay đổi/thêm mới

### 1. `story_generator.py` - Module chính
**Thêm mới**:
- `StoryPrompts.VA_MAT`: Dictionary chứa prompts cho thể loại vả mặt
  - `system`: System prompt cho AI
  - `user_template`: Template prompt chính
  - `themes`: 10 chủ đề gợi ý
  - `vai_tro_gia`: 13 vai trò giả
  - `settings`: 10 bối cảnh

- `generate_face_slap_story()`: Method tạo truyện vả mặt
  - Tham số: theme, vai_tro_gia, setting, custom_requirements, max_tokens, temperature
  - Cấu trúc 10 chương tương tự truyện kinh dị
  - Ngôi kể thứ nhất
  - Nhiều hội thoại, tiết tấu nhanh
  
- `_extract_title_face_slap()`: Helper extract title cho truyện vả mặt

- `_save_story_face_slap()`: Helper lưu file truyện vả mặt
  - Format file: `YYYYMMDD_HHMMSS_vamat_<title>.txt`
  - Metadata bao gồm: thể loại, chủ đề, vai trò giả, bối cảnh

### 2. `demo_create_face_slap.py` - NEW
Script demo nhanh tạo truyện vả mặt
- Model mặc định: gpt-4o-mini
- Chọn ngẫu nhiên theme/vai_tro/setting

### 3. `test_face_slap_generator.py` - NEW  
Script test tương tác với menu
- Chọn model AI
- Menu lựa chọn: ngẫu nhiên, chọn theme, vai trò, bối cảnh
- Tạo nhiều truyện liên tục

### 4. `GUIDE_FACE_SLAP.md` - NEW
Tài liệu hướng dẫn chi tiết
- Cách sử dụng
- Danh sách themes/vai_tro/settings
- So sánh với thể loại kinh dị
- Troubleshooting

## 🎯 Chi tiết thể loại VẢ MẶT

### Cấu trúc truyện (10 chương ~10,000 từ)

1. **Phần 1** (800 từ): Giới thiệu nhân vật trong thân phận giả
2. **Phần 2** (800 từ): Bị coi thường, phản ứng hài hước
3. **Phần 3** (1200 từ): Tình huống "tấu hài", dở khóc dở cười
4. **Phần 4** (1200 từ): Căng thẳng hơn, có "phản đòn" tinh tế
5. **Phần 5** (1000 từ): Manh mối đầu tiên về thân phận thật
6. **Phần 6** (1200 từ): Sự kiện quan trọng sắp xảy ra
7. **Phần 7** (1200 từ): Thân phận thật sắp lộ ra
8. **Phần 8** (1000 từ): **VẢ MẶT** - thân phận tiết lộ
9. **Phần 9** (1200 từ): Hậu quả, người khác xin lỗi
10. **Phần 10** (1000 từ): Kết thúc ý nghĩa, câu thoại chất

### Phong cách viết

- **Ngôi kể**: Ngôi thứ nhất ("tôi")
- **Tông giọng**: Hài hước, nhẹ nhàng, hiện đại
- **Hội thoại**: Nhiều, sống động, "bắt trend"
- **Miêu tả**: Ít, tập trung cảm xúc
- **Tiết tấu**: Nhanh, vui nhộn
- **Kết thúc**: Hả hê nhưng văn minh, có thông điệp

### 10 Chủ đề có sẵn

1. Shipper nghèo → Chủ tịch công ty
2. Thực tập sinh → Nhà đầu tư lớn nhất
3. Cô gái giản dị → Người thừa kế tập đoàn
4. Freelancer → Người đứng sau nền tảng
5. Học sinh nghèo → Con ông chủ trường
6. Nhân viên tạp vụ → CEO ẩn danh
7. Bảo vệ → Chủ tòa nhà
8. Phục vụ cafe → Chủ chuỗi cafe
9. Sinh viên dạy kèm → Giáo sư trẻ nhất
10. Tài xế taxi → Ông chủ hãng xe

### 13 Vai trò giả

shipper, thực tập sinh, nhân viên bán hàng, freelancer, học sinh, nhân viên tạp vụ, bảo vệ, phục vụ cafe, sinh viên dạy kèm, tài xế taxi, nhân viên giao hàng, thợ sửa xe, lập trình viên mới

### 10 Bối cảnh

công ty lớn, showroom xe, trường đại học, chung cư cao cấp, cửa hàng thời trang, khách sạn 5 sao, startup, trung tâm thương mại, tập đoàn đa quốc gia, gala từ thiện

## 💻 Cách sử dụng

### Tạo nhanh
```bash
python demo_create_face_slap.py
```

### Tạo tương tác
```bash
python test_face_slap_generator.py
```

### Code Python
```python
from story_generator import StoryGenerator

generator = StoryGenerator(model="gpt-4o-mini")

# Ngẫu nhiên
result = generator.generate_face_slap_story()

# Tùy chỉnh
result = generator.generate_face_slap_story(
    theme="Anh shipper nghèo...",
    vai_tro_gia="shipper giao đồ ăn",
    setting="công ty lớn"
)
```

## 🆚 So sánh 2 thể loại

| Đặc điểm | Kinh Dí | Vả Mặt |
|----------|---------|--------|
| Function | `generate_horror_story()` | `generate_face_slap_story()` |
| Tông giọng | Ma mị, u ám | Hài hước, nhẹ nhàng |
| Tiết tấu | Chậm rãi | Nhanh |
| Hội thoại | Ít | Nhiều |
| Miêu tả | Chi tiết khí quyển | Chi tiết cảm xúc |
| Kết thúc | Twist ám ảnh | Hả hê có ý nghĩa |
| Prompts | `StoryPrompts.KINH_DI` | `StoryPrompts.VA_MAT` |

## ⚙️ Thay đổi kỹ thuật

### System Prompt cho Vả Mặt
```
- Nhà văn chuyên "vả mặt - face slap"
- Phong cách hài hước, nhẹ nhàng nhưng hả hê
- Tạo tình huống dở khóc dở cười
- Khoảnh khắc twist "đỉnh cao"
- Vibe phim Hàn/Trung về vả mặt văn minh
```

### Cấu trúc Chapter
- Mỗi chapter có prompt riêng, độc lập
- Summary 150 từ giữa các chapter
- Không lưu conversation history
- Dynamic max_tokens theo model

### File Output
- Prefix: `vamat_` để phân biệt
- Metadata: genre="va_mat", vai_tro_gia, setting
- Format: Không có tiêu đề ##, phù hợp audio

## 📊 Model Performance

| Model | Cost/story | Quality | Speed |
|-------|-----------|---------|-------|
| gpt-4o-mini | $0.02 | Good | Fast |
| gpt-4o | $0.52 | Very Good | Medium |
| gpt-4-turbo | $0.60 | Excellent | Medium |

## 🎯 Next Steps (Tương lai)

- [ ] Thêm thể loại "Xuyên không"
- [ ] Thêm thể loại "Trọng sinh"
- [ ] Thêm thể loại "Tu tiên"
- [ ] Support multi-language
- [ ] Web UI để tạo truyện
- [ ] API endpoint

## 📌 Notes

- Cả 2 thể loại (Kinh Dị + Vả Mặt) đều kể theo ngôi thứ nhất
- Cả 2 đều không có tiêu đề ## trong nội dung (phù hợp audio)
- Cả 2 đều chia 10 chương độc lập
- Code structure tương tự, dễ mở rộng thêm thể loại mới

## ✅ Checklist hoàn thành

- [x] Thêm StoryPrompts.VA_MAT
- [x] Implement generate_face_slap_story()
- [x] Thêm helper methods (_extract_title_face_slap, _save_story_face_slap)
- [x] Tạo demo_create_face_slap.py
- [x] Tạo test_face_slap_generator.py
- [x] Tạo GUIDE_FACE_SLAP.md
- [x] Tạo CHANGELOG

---

**Tổng kết**: Đã thành công thêm thể loại "Vả Mặt" vào hệ thống tạo truyện. Người dùng giờ có thể tạo 2 loại truyện: Kinh Dị và Vả Mặt, với code structure dễ mở rộng cho các thể loại khác trong tương lai.

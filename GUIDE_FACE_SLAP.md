# HƯỚNG DẪN TẠO TRUYỆN VẢ MẶT - FACE SLAP

## 🎭 Giới thiệu

Thể loại **"Vả mặt - Face Slap"** là truyện đô thị hiện đại, hài hước, với concept:
- Nhân vật chính giàu/có địa vị cao giả làm người bình thường
- Bị người khác coi thường vì vẻ ngoài giản dị
- Cuối cùng thân phận thật được tiết lộ → "vả mặt" cực hả hê
- Thông điệp: "Đừng đánh giá người qua bề ngoài"

## 📦 Các file quan trọng

```
story_generator.py         # Module chính (đã cập nhật hỗ trợ thể loại vả mặt)
demo_create_face_slap.py   # Demo nhanh tạo truyện vả mặt
test_face_slap_generator.py # Script test tương tác (menu)
```

## 🚀 Cách sử dụng

### 1. Tạo truyện nhanh (ngẫu nhiên)

```bash
python demo_create_face_slap.py
```

Truyện sẽ được tạo với:
- Chủ đề ngẫu nhiên
- Vai trò giả ngẫu nhiên  
- Bối cảnh ngẫu nhiên
- Model: gpt-4o-mini (rẻ nhất)

### 2. Tạo truyện tương tác (chọn lựa)

```bash
python test_face_slap_generator.py
```

Menu cho phép:
- Chọn model AI
- Chọn chủ đề từ 10 gợi ý
- Chọn vai trò giả từ 13 gợi ý
- Chọn bối cảnh từ 10 gợi ý
- Hoặc để ngẫu nhiên

### 3. Code Python tùy chỉnh

```python
from story_generator import StoryGenerator

# Khởi tạo với model
generator = StoryGenerator(model="gpt-4o-mini")

# Tạo truyện ngẫu nhiên
result = generator.generate_face_slap_story()

# Hoặc tùy chỉnh
result = generator.generate_face_slap_story(
    theme="Anh shipper nghèo bị cô tiểu thư chê bai, hóa ra là chủ tịch công ty cô làm việc.",
    vai_tro_gia="shipper giao đồ ăn",
    setting="công ty lớn ở trung tâm thành phố",
    custom_requirements="Thêm cảnh vả mặt cực mạnh ở cuối"
)

print(f"Tiêu đề: {result['title']}")
print(f"Độ dài: {result['word_count']} từ")
print(f"File: {result['file_path']}")
```

## 🎯 Danh sách chủ đề có sẵn

1. Anh shipper nghèo bị cô tiểu thư chê bai, hóa ra là chủ tịch công ty cô làm việc.
2. Thực tập sinh bị sếp mắng ngu, nhưng lại là nhà đầu tư lớn nhất của công ty.
3. Cô gái giản dị đi mua xe, bị nhân viên bán hàng coi thường, hóa ra là người thừa kế tập đoàn.
4. Freelancer bị từ chối hợp tác, ai ngờ chính là người đứng sau nền tảng họ đang dùng.
5. Học sinh nghèo bị bạn học giàu nhạo báng, hóa ra là con của ông chủ trường.
6. Nhân viên tạp vụ bị đồng nghiệp khinh thường, thật ra là CEO ẩn danh đang khảo sát.
7. Anh bảo vệ bị cư dân chung cư coi thường, hóa ra là chủ tòa nhà.
8. Cô phục vụ quán cafe bị khách hàng mắng, thật ra là chủ chuỗi cafe đó.
9. Sinh viên dạy kèm bị phụ huynh chê, nhưng lại là giáo sư trẻ nhất nước.
10. Tài xế taxi bị khách xem thường, hoá ra là ông chủ hãng xe công nghệ đó.

## 👤 Vai trò giả có sẵn

- shipper giao đồ ăn
- thực tập sinh văn phòng
- nhân viên bán hàng
- freelancer thiết kế
- học sinh trường công
- nhân viên tạp vụ
- bảo vệ tòa nhà
- phục vụ quán cafe
- sinh viên dạy kèm
- tài xế taxi
- nhân viên giao hàng
- thợ sửa xe
- lập trình viên mới vào nghề

## 🏢 Bối cảnh có sẵn

- công ty lớn ở trung tâm thành phố
- showroom xe hơi sang trọng
- trường đại học danh giá
- tòa nhà chung cư cao cấp
- chuỗi cửa hàng thời trang
- khách sạn 5 sao
- công ty công nghệ startup
- trung tâm thương mại lớn
- văn phòng tập đoàn đa quốc gia
- buổi gala từ thiện giới thượng lưu

## ⚙️ Model khuyến nghị

| Model | Chi phí/truyện | Chất lượng | Khuyến nghị |
|-------|---------------|-----------|-------------|
| gpt-4o-mini | ~$0.02 | Tốt | ✅ Rẻ nhất, đủ dùng |
| gpt-4o | ~$0.52 | Rất tốt | ⭐ Cân bằng tốt |
| gpt-4-turbo | ~$0.60 | Xuất sắc | 💎 Chất lượng cao nhất |

## 📊 Đặc điểm truyện

- **Độ dài**: ~10,000 từ (10 chương)
- **Ngôi kể**: Ngôi thứ nhất ("tôi")
- **Phong cách**: Hài hước, hiện đại, gần gũi
- **Hội thoại**: Nhiều, sống động, "bắt trend"
- **Tiết tấu**: Nhanh, vui nhộn
- **Kết thúc**: Hả hê, có ý nghĩa

## 📁 Output

Truyện được lưu tại: `stories/YYYYMMDD_HHMMSS_vamat_<title>.txt`

Format file:
```
================================================================================
TIÊU ĐỀ: <title>
================================================================================

Thể loại: Vả Mặt - Face Slap
Chủ đề: ...
Vai trò giả: ...
Bối cảnh: ...
Thời gian tạo: ...

================================================================================

<nội dung truyện - không có tiêu đề phần>

================================================================================
Kết thúc truyện
================================================================================
```

## 💡 Tips

1. **Chọn model phù hợp**: Dùng gpt-4o-mini cho test, gpt-4o cho production
2. **Kết hợp chủ đề**: Có thể tự nghĩ chủ đề mới, không bắt buộc dùng có sẵn
3. **Thêm yêu cầu**: Dùng `custom_requirements` để thêm chi tiết đặc biệt
4. **Kiểm tra output**: Đọc file trong thư mục `stories/`
5. **Audio truyện**: File không có tiêu đề phần ##, phù hợp để tạo audio

## 🆚 So sánh với thể loại Kinh Dị

| Đặc điểm | Kinh Dị | Vả Mặt |
|----------|---------|--------|
| Tông giọng | Ma mị, u ám | Hài hước, nhẹ nhàng |
| Ngôi kể | Ngôi thứ nhất | Ngôi thứ nhất |
| Tiết tấu | Chậm rãi | Nhanh |
| Hội thoại | Ít | Nhiều |
| Kết thúc | Twist, ám ảnh | Hả hê, ý nghĩa |
| Function | `generate_horror_story()` | `generate_face_slap_story()` |

## 🐛 Troubleshooting

**Lỗi API key**:
```python
generator = StoryGenerator(
    model="gpt-4o-mini",
    api_key="your-api-key-here"
)
```

**Truyện quá ngắn**: Tăng `max_tokens` hoặc dùng model lớn hơn

**Lỗi rate limit**: Thêm delay giữa các lần tạo

**File không lưu được**: Kiểm tra quyền ghi thư mục `stories/`

## 📞 Support

Nếu có vấn đề, kiểm tra:
1. Discord logs (nếu có tích hợp)
2. File `generation_history.json` trong thư mục `stories/`
3. Console output khi chạy

---

**Chúc bạn tạo được nhiều truyện vả mặt hả hê! 🎉**

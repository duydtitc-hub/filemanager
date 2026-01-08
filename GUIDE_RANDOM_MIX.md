# 🎲 HƯỚNG DẪN TRUYỆN RANDOM MIX

## 🎭 Giới thiệu

**RANDOM MIX** là thể loại đặc biệt kết hợp ngẫu nhiên nhiều yếu tố:
- 🎭 Thể loại chính (10 loại)
- 🎨 Thể loại phụ (10 loại)
- 👤 Nhân vật archetype (10 loại)
- 🏙️ Bối cảnh (10 loại)
- 📖 Mô típ cốt truyện (6 loại)

→ **Tổng cộng: 10 × 10 × 10 × 10 × 6 = 600,000 kết hợp có thể!**

## 🎯 Đặc điểm

### Phong cách
- Hài hước + Kinh dị + Vả mặt + Siêu nhiên + Hiện đại
- Rùng rợn nhẹ nhưng vẫn cười được
- Châm biếm xã hội tinh tế
- Twist cuối BẮT BUỘC phải bất ngờ

### Cấu trúc
- **10 chương** (~10,000 từ)
- **Ngôi thứ nhất** ("tôi")
- **Không tiêu đề ##** (phù hợp audio)
- Temperature cao (0.9) → Sáng tạo hơn

### Kết thúc
- TWIST cuối cùng bất ngờ (bắt buộc!)
- Câu thoại đỉnh cao
- Kết mở hoặc đóng
- Dư vị suy ngẫm

## 📦 Sử dụng

### 1. Demo nhanh (Random toàn bộ)

```bash
python demo_create_random_mix.py
```

AI sẽ tự chọn ngẫu nhiên:
- Thể loại chính
- Thể loại phụ  
- Nhân vật
- Bối cảnh
- Mô típ

### 2. Test tương tác (Chọn lựa)

```bash
python test_random_mix_generator.py
```

Menu cho phép:
- Random hoàn toàn
- Chọn từng yếu tố
- Tùy chỉnh toàn bộ

### 3. Code Python

```python
from story_generator import StoryGenerator

generator = StoryGenerator(model="gpt-4o-mini")

# Random hoàn toàn
result = generator.generate_random_mix_story()

# Chọn 1 yếu tố, random còn lại
result = generator.generate_random_mix_story(
    the_loai_chinh="Streamer đời thực"
)

# Tùy chỉnh toàn bộ
result = generator.generate_random_mix_story(
    the_loai_chinh="AI trừ tà",
    the_loai_phu="Tình cảm – nhận thức – nhân tính",
    nhan_vat="🤖 AI tự nhận thức: Hỗ trợ điều tra siêu nhiên...",
    boi_canh="🏢 Cục điều tra siêu nhiên...",
    mo_tip="Công nghệ và tâm linh va chạm..."
)

print(f"Tiêu đề: {result['title']}")
print(f"File: {result['file_path']}")
```

## 🎭 10 Thể loại chính

1. **Kinh dị hiện đại** - Horror đô thị
2. **Hành động điều tra** - Detective + Action
3. **Chủ tịch giả nghèo** - Undercover Boss
4. **Lãng mạn ngược đời** - Romance twist
5. **Streamer đời thực** - Social media reality
6. **Hacker tâm linh** - Cyber + Supernatural
7. **Thực tập sinh bí ẩn** - Hidden identity intern
8. **Nhà văn bị ám** - Cursed writer
9. **AI trừ tà** - AI exorcist
10. **Cục điều tra siêu nhiên** - Paranormal investigation

## 🎨 10 Thể loại phụ (Kết hợp)

1. **Hài đen** (dark comedy)
2. **Siêu nhiên học** (paranormal studies)
3. **Khoa học tâm linh** (spiritual science)
4. **Trừ tà học / Ma học** (exorcism / demonology)
5. **Phát hiện linh hồn qua công nghệ** (tech + ghosts)
6. **Thế giới ngầm công nghệ** (cyber underground)
7. **Tổ chức siêu nhiên quốc tế** (paranormal agency)
8. **Hài – twist – ảo thực** (comedy + surreal)
9. **Tình cảm – nhận thức – nhân tính** (emotion + humanity)
10. **Chính trị / Xã hội ngầm** (politics + underground)

## 👤 10 Nhân vật archetype

1. **👨‍💼 Chủ tịch giả nghèo**
   - Vẻ ngoài nhạt nhòa, IQ cao, EQ thấp
   - Thử lòng người, phản ứng cực tỉnh

2. **👮 Điều tra viên tân binh**
   - Giám đốc ngầm Cục Điều Tra Siêu Nhiên
   - Xuống cơ sở kiểm tra

3. **👻 Streamer bắt ma**
   - Livestream trừ tà
   - Khán giả tưởng giả → gặp ma thật

4. **🤖 AI tự nhận thức**
   - Hỗ trợ điều tra siêu nhiên
   - Học cảm xúc, thấy "thứ gì đó" trong data

5. **💻 Hacker tâm linh**
   - Phát hiện linh hồn trong dữ liệu mạng
   - Đối đầu "mã độc ma quỷ"

6. **🧘 Thầy bói công nghệ**
   - AI + tarot đoán nghiệp báo
   - Chính mình bị dự đoán

7. **🧑‍🔬 Nhà khoa học vô thần**
   - Không tin ma
   - Thí nghiệm tạo hiện tượng vượt logic

8. **💅 Kim chủ giản dị**
   - Giàu có hoà vào đám đông
   - Bị khinh thường → lộ thân phận

9. **🧑‍🎓 Thực tập sinh ngây thơ**
   - Dễ thương, vụng về
   - Người duy nhất hiểu sự thật

10. **📖 Tác giả bị ám**
    - Truyện viết ra xảy ra thật
    - Sợ ngòi bút của mình

## 🏙️ 10 Bối cảnh

1. **🏢 Cục điều tra siêu nhiên**
   - Khoa học + tâm linh gặp nhau

2. **🏢 Công ty công nghệ tâm linh**
   - Startup AI + trừ tà

3. **🏙️ Quán café hoạt động sau nửa đêm**
   - Khách hàng đặc biệt

4. **🏙️ Khách sạn chỉ mở lúc 3h sáng**
   - "Những người đặc biệt" nghỉ ngơi

5. **📡 Kênh livestream bắt ma**
   - 100k người xem mỗi đêm

6. **📡 Group Facebook "Chuyện Lạ Thật"**
   - 2 triệu thành viên

7. **🏫 Học viện nghiên cứu siêu hình học**
   - Thử nghiệm khoa học + ma thuật

8. **🏫 Viện nghiên cứu AI tâm linh**
   - Dạy robot nhận diện linh hồn

9. **🧩 Hội kín nghiên cứu cõi âm**
   - Giới nhà giàu chơi bùa

10. **🧩 Công ty công nghệ xuyên linh hồn**
    - Gặp người đã khuất qua VR

## 📖 6 Mô típ cốt truyện

1. **Vả mặt cực mạnh**
   - Bị coi thường → lộ thân phận → sững sờ

2. **Bắt ma giả gặp ma thật**
   - Livestream dàn dựng → gặp hàng thật

3. **Công nghệ và tâm linh va chạm**
   - AI phát hiện linh hồn, robot bị ám

4. **Hài đen xã hội**
   - Cười ra nước mắt – người đáng sợ hơn ma

5. **Niềm tin và nỗi sợ**
   - Không tin ma lại gặp nhiều nhất

6. **Thử lòng / kiểm tra nhân phẩm**
   - Giả nghèo – thử lòng – vả mặt – twist

## 💡 Ví dụ kết hợp hay

### Combo 1: Streamer meets Tech Ghost
- Thể loại chính: Streamer đời thực
- Thể loại phụ: Phát hiện linh hồn qua công nghệ
- Nhân vật: Streamer bắt ma
- Bối cảnh: Kênh livestream
- Mô típ: Bắt ma giả gặp ma thật

### Combo 2: AI Detective Romance
- Thể loại chính: AI trừ tà
- Thể loại phụ: Tình cảm – nhận thức – nhân tính
- Nhân vật: AI tự nhận thức
- Bối cảnh: Cục điều tra siêu nhiên
- Mô típ: Công nghệ và tâm linh va chạm

### Combo 3: Boss Undercover Paranormal
- Thể loại chính: Chủ tịch giả nghèo
- Thể loại phụ: Tổ chức siêu nhiên quốc tế
- Nhân vật: Chủ tịch giả nghèo
- Bối cảnh: Công ty công nghệ tâm linh
- Mô típ: Vả mặt cực mạnh

## ⚙️ Model khuyến nghị

| Model | Chi phí | Sáng tạo | Khuyến nghị |
|-------|---------|----------|-------------|
| gpt-4o-mini | $0.02 | Tốt | ✅ Test |
| gpt-4o | $0.52 | Rất tốt | ⭐ Production |
| gpt-4-turbo | $0.60 | Xuất sắc | 💎 Premium |

**Note**: Random Mix dùng temperature=0.9 (cao) nên cần model tốt!

## 📁 Output

File: `stories/YYYYMMDD_HHMMSS_random_<title>.txt`

Format:
```
================================================================================
TIÊU ĐỀ: <title>
================================================================================

Thể loại: RANDOM MIX (Hài - Kinh dị - Vả mặt - Siêu nhiên - Hiện đại)
Thể loại chính: ...
Thể loại phụ: ...
Nhân vật: ...
Bối cảnh: ...
Mô típ: ...

================================================================================

<nội dung truyện - không có tiêu đề ##>

================================================================================
```

## 🆚 So sánh với thể loại khác

| Đặc điểm | Kinh Dị | Vả Mặt | Random Mix |
|----------|---------|--------|------------|
| Tông giọng | Ma mị | Hài hước | Kết hợp linh hoạt |
| Yếu tố | Siêu nhiên | Xã hội | Đa dạng |
| Twist | Ám ảnh | Hả hê | Bất ngờ |
| Temperature | 0.8 | 0.85 | 0.9 |
| Kết hợp | Đơn | Đơn | Nhiều |

## 💡 Tips

1. **Random hoàn toàn**: Cho kết quả bất ngờ nhất
2. **Chọn 1-2 yếu tố**: Cân bằng giữa control và surprise
3. **Tùy chỉnh toàn bộ**: Khi có ý tưởng cụ thể
4. **Dùng model tốt**: Temperature cao cần model mạnh
5. **Đọc thử**: Random Mix có thể rất độc đáo!

## 🔥 Thử ngay!

```bash
python demo_create_random_mix.py
```

Mỗi lần chạy = 1 truyện hoàn toàn khác biệt!

---

**600,000 khả năng đang chờ bạn khám phá! 🎲✨**

# Story Generator - Tạo Truyện Ngắn Tự Động

Module tạo truyện ngắn tự động bằng ChatGPT-5 Pro (hoặc GPT-4).
Hỗ trợ nhiều thể loại, hiện tại tập trung vào **Kinh Dị - Huyền Bí - Linh Dị Việt Nam**.

## 📋 Tính Năng

- ✅ Tạo truyện ngắn kinh dị độ dài ~10.000 từ
- ✅ Nhiều chủ đề và bối cảnh sẵn có (hoặc tùy chỉnh)
- ✅ Phong cách viết ma mị, u ám, tinh tế theo phong cách Việt Nam
- ✅ Cấu trúc rõ ràng: Mở đầu → Phát triển → Cao trào → Đỉnh điểm → Kết thúc
- ✅ Twist bất ngờ và kết mở ám ảnh
- ✅ Lưu trữ lịch sử và thống kê
- ✅ Hỗ trợ tạo hàng loạt với delay tự động

## 🚀 Cài Đặt

```bash
pip install openai
```

## 📖 Sử Dụng

### Cách 1: Sử dụng hàm tiện ích (Đơn giản nhất)

```python
from story_generator import create_horror_story

# Tạo truyện với chủ đề và bối cảnh ngẫu nhiên
result = create_horror_story()

print(result['title'])
print(result['content'])
print(f"Số từ: {result['word_count']:,}")
print(f"Đã lưu tại: {result['file_path']}")
```

### Cách 2: Sử dụng class StoryGenerator (Linh hoạt)

```python
from story_generator import StoryGenerator

# Khởi tạo generator
generator = StoryGenerator(model="gpt-4")

# Tạo truyện với chủ đề cụ thể
result = generator.generate_horror_story(
    theme='Làng cổ có lời nguyền "không ai được gọi tên người chết".',
    setting="làng quê xa xôi miền Bắc",
    temperature=0.85  # Độ sáng tạo (0.0-1.0)
)

print(result['title'])
print(result['content'])
```

### Cách 3: Tạo nhiều truyện liên tiếp

```python
from story_generator import StoryGenerator

generator = StoryGenerator(model="gpt-4")

# Tạo 5 truyện với delay 10 giây giữa các lần
results = generator.generate_multiple_stories(
    count=5,
    delay_between=10,
    temperature=0.8
)

for i, result in enumerate(results, 1):
    print(f"{i}. {result['title']}: {result['word_count']:,} từ")
```

### Cách 4: Thêm yêu cầu tùy chỉnh

```python
from story_generator import StoryGenerator

generator = StoryGenerator(model="gpt-4")

custom_req = """
- Nhân vật chính là một nhà báo điều tra
- Có yếu tố công nghệ hiện đại (điện thoại, camera, mạng xã hội)
- Kết thúc mở, gợi ý câu chuyện có thể tiếp tục
- Xuất hiện ít nhất 3 nhân vật phụ với vai trò rõ ràng
"""

result = generator.generate_horror_story(
    theme="Người thu âm podcast nghe thấy giọng mình thì thầm trong băng khi không hề nói.",
    setting="đô thị hiện đại",
    custom_requirements=custom_req
)
```

## 📊 Thống Kê

```python
from story_generator import StoryGenerator

generator = StoryGenerator()
stats = generator.get_story_statistics()

print(f"Tổng số truyện: {stats['total_stories']}")
print(f"Tổng số từ: {stats['total_words']:,}")
print(f"Trung bình: {stats['average_words']:,} từ/truyện")
```

## 🎭 Chủ Đề Có Sẵn

1. Làng cổ có lời nguyền "không ai được gọi tên người chết"
2. Bệnh viện bỏ hoang – nơi một y tá vẫn làm việc mỗi đêm
3. Căn phòng trọ số 13, nơi gương không bao giờ phản chiếu đúng hình người
4. Trường học xây trên nền nghĩa địa
5. Bức ảnh gia đình mà gương mặt thứ năm không ai biết là ai
6. Người thu âm podcast nghe thấy giọng mình thì thầm trong băng khi không hề nói
7. Ngôi nhà cổ bên sông, nơi mỗi đêm trăng rằm có tiếng hát ru ám ảnh
8. Chiếc xe buýt cuối cùng, nơi hành khách không bao giờ xuống
9. Căn hầm dưới nhà thờ cổ, nơi lưu giữ những lời cầu nguyện ngược
10. Cây đa nghìn năm tuổi, nơi mọi người tự tử đều để lại lời nhắn giống hệt nhau

## 🌍 Bối Cảnh Có Sẵn

1. Làng quê xa xôi miền Bắc
2. Đô thị hiện đại nhưng có khu cũ ẩn chứa bí mật
3. Tu viện bỏ hoang trên núi
4. Ngôi nhà cổ bên sông
5. Trại giam bỏ hoang từ thời chiến tranh
6. Bệnh viện tâm thần cũ
7. Trường học nội trú vùng núi
8. Khu tập thể cũ sắp được phá dỡ
9. Nghĩa trang xe cổ ven đường
10. Hầm trú ẩn thời chiến tranh

## 🧪 Chạy Test

```bash
# Chạy test menu
python test_story_generator.py

# Hoặc test cụ thể trong code
python story_generator.py
```

## 📁 Cấu Trúc File

```
TTSDocker/
├── story_generator.py          # Module chính
├── test_story_generator.py     # File test và demo
├── README_STORY_GENERATOR.md   # File này
└── stories/                     # Thư mục lưu truyện (tự động tạo)
    ├── 20241111_120000_Truyen_Kinh_Di_1.txt
    ├── 20241111_120530_Truyen_Kinh_Di_2.txt
    └── generation_history.json  # Lịch sử tạo truyện
```

## ⚙️ Tham Số

### StoryGenerator.__init__()
- `model` (str): Model OpenAI sử dụng (mặc định: "gpt-4")
  - Có thể dùng: "gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"
- `api_key` (str, optional): API key OpenAI (nếu không truyền sẽ dùng key mặc định)

### generate_horror_story()
- `theme` (str, optional): Chủ đề truyện (None = ngẫu nhiên)
- `setting` (str, optional): Bối cảnh (None = ngẫu nhiên)
- `custom_requirements` (str, optional): Yêu cầu tùy chỉnh thêm
- `max_tokens` (int): Số token tối đa (mặc định: 16000)
- `temperature` (float): Độ sáng tạo 0.0-1.0 (mặc định: 0.8)

### generate_multiple_stories()
- `count` (int): Số truyện cần tạo
- `delay_between` (int): Giây chờ giữa các lần (tránh rate limit)
- `**kwargs`: Các tham số khác của generate_horror_story()

## 📝 Kết Quả Trả Về

```python
{
    'title': str,              # Tiêu đề truyện
    'content': str,            # Nội dung đầy đủ
    'theme': str,              # Chủ đề
    'setting': str,            # Bối cảnh
    'word_count': int,         # Số từ
    'generation_time': float,  # Thời gian tạo (giây)
    'file_path': str,          # Đường dẫn file đã lưu
    'metadata': {
        'model': str,
        'timestamp': float,
        'tokens_used': int,
        ...
    }
}
```

## 🎯 Yêu Cầu Về Truyện

### Phong Cách
- Ma mị, u ám, tinh tế
- Không máu me hay bạo lực quá đà
- Tập trung vào nỗi sợ tâm linh, ám ảnh, cảm giác lạnh gáy
- Ngôn ngữ tự nhiên, có tính địa phương

### Cấu Trúc (Tổng ~10.000 từ)
1. **Mở đầu** (~1.000 từ): Giới thiệu nhân vật, bối cảnh
2. **Phát triển** (~3.000 từ): Hiện tượng bất thường xuất hiện
3. **Cao trào** (~3.000 từ): Tìm ra manh mối
4. **Đỉnh điểm** (~2.000 từ): Sự thật được hé lộ
5. **Kết thúc** (~1.000 từ): Twist hoặc kết mở

### Chi Tiết Ám Ảnh
Mỗi đoạn có ít nhất một chi tiết:
- Âm thanh: tiếng thì thầm, tiếng bước chân, gió...
- Ánh sáng: bóng người, ánh mắt, đèn nhấp nháy...
- Mùi: mùi hương lạ, mùi ẩm mốc, mùi hoa...
- Cảm giác: lạnh, nóng, ngứa ran, tê tái...

## 🔧 Cấu Hình API

Thay đổi API key trong `story_generator.py`:

```python
openai.api_key = "YOUR_API_KEY_HERE"
```

Hoặc truyền vào khi khởi tạo:

```python
generator = StoryGenerator(api_key="YOUR_API_KEY_HERE")
```

## 💡 Tips

1. **Tối ưu chi phí**: Dùng `gpt-3.5-turbo` cho test, `gpt-4` cho sản phẩm cuối
2. **Tăng độ sáng tạo**: Tăng `temperature` (0.8-0.95)
3. **Ổn định hơn**: Giảm `temperature` (0.5-0.7)
4. **Tránh rate limit**: Tăng `delay_between` khi tạo hàng loạt
5. **Custom theme**: Viết theme riêng thay vì dùng có sẵn

## 🐛 Troubleshooting

### Lỗi: "Rate limit exceeded"
→ Tăng `delay_between` hoặc nâng cấp plan OpenAI

### Truyện quá ngắn (<8000 từ)
→ Tăng `max_tokens` lên 20000 hoặc thêm yêu cầu về độ dài trong `custom_requirements`

### Truyện không đủ kinh dị
→ Tăng `temperature` và thêm yêu cầu cụ thể về yếu tố kinh dị

### File không lưu được
→ Kiểm tra quyền ghi vào thư mục `stories/`

## 📞 Support

Nếu gặp vấn đề, kiểm tra:
1. API key có hợp lệ không
2. Đủ credit trong tài khoản OpenAI không
3. Kết nối internet ổn định không

## 🔮 Tương Lai

- [ ] Hỗ trợ thêm thể loại: Lãng mạn, Trinh thám, Khoa học viễn tưởng
- [ ] Tích hợp TTS để tạo audiobook tự động
- [ ] Web UI để tạo truyện qua giao diện
- [ ] Export sang nhiều format: PDF, EPUB, MOBI
- [ ] Fine-tune model với phong cách tác giả Việt Nam

## 📄 License

MIT License - Tự do sử dụng và chỉnh sửa.

---

**Tác giả**: AI Story Generator Team  
**Ngày tạo**: 2024-11-11  
**Version**: 1.0.0

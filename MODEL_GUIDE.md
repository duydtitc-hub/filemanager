# Hướng Dẫn Chọn Model OpenAI

## 📊 So Sánh Các Model

| Model | Context Length | Max Output | Giá (1M tokens) | Khuyến nghị | Ghi chú |
|-------|---------------|------------|-----------------|-------------|---------|
| **gpt-4-turbo** | 128k | 16k | $10/$30 | ⭐⭐⭐ Tốt nhất | Lý tưởng cho truyện dài |
| **gpt-4o** | 128k | 16k | $5/$15 | ⭐⭐⭐ Tốt nhất | Giống turbo, rẻ hơn |
| **gpt-4o-mini** | 128k | 12k | $0.15/$0.6 | ⭐⭐ Tốt | Rất rẻ, chất lượng OK |
| **gpt-3.5-turbo-16k** | 16k | 4k | $0.5/$1.5 | ⭐⭐ Tốt | Rẻ, đủ cho truyện ngắn |
| **gpt-4** | 8k | 6k | $30/$60 | ⚠️ KHÔNG khuyến nghị | Context nhỏ, đắt |

**Giá**: Input / Output (per 1M tokens)

## 🎯 Khuyến Nghị Theo Nhu Cầu

### ✅ Truyện 10.000 từ (Khuyến nghị)
```python
generator = StoryGenerator(model="gpt-4-turbo")
# HOẶC
generator = StoryGenerator(model="gpt-4o")
```
- **Ưu điểm**: Context lớn (128k), chất lượng cao, ổn định
- **Chi phí**: ~$0.30-0.50 / truyện

### 💰 Tiết Kiệm Chi Phí (Vẫn tốt)
```python
generator = StoryGenerator(model="gpt-4o-mini")
# HOẶC
generator = StoryGenerator(model="gpt-3.5-turbo-16k")
```
- **Ưu điểm**: Rất rẻ (~$0.02-0.05 / truyện)
- **Nhược điểm**: Chất lượng không bằng GPT-4, có thể thiếu sáng tạo

### ❌ TRÁNH Dùng
```python
generator = StoryGenerator(model="gpt-4")  # Context chỉ 8k!
```
- **Vấn đề**: Context quá nhỏ → PHẢI chia thành nhiều chương → mất mạch truyện

## 🔧 Cấu Hình Chi Tiết

### Model Config trong Code

```python
MODEL_CONFIGS = {
    "gpt-4": {
        "max_context": 8192,
        "safe_completion": 6000  # Để lại buffer cho prompt
    },
    "gpt-4-turbo": {
        "max_context": 128000,
        "safe_completion": 16000
    },
    "gpt-4o": {
        "max_context": 128000,
        "safe_completion": 16000
    },
    "gpt-4o-mini": {
        "max_context": 128000,
        "safe_completion": 12000
    },
    "gpt-3.5-turbo-16k": {
        "max_context": 16385,
        "safe_completion": 12000
    }
}
```

## 🎨 Phương Pháp Tạo Truyện

### Cách 1: Chia Thành 5 Chương (Hiện tại)
```python
# Truyện được tạo qua 5 API calls riêng biệt:
# 1. Mở đầu (~1000 từ)
# 2. Phát triển (~3000 từ)
# 3. Cao trào (~3000 từ)
# 4. Đỉnh điểm (~2000 từ)
# 5. Kết thúc (~1000 từ)

result = generator.generate_horror_story()
```

**Ưu điểm**:
- ✅ Tránh vượt giới hạn token
- ✅ Giữ được mạch truyện qua conversation history
- ✅ Hoạt động với MỌI model

**Nhược điểm**:
- ⚠️ Mất thời gian hơn (5 API calls)
- ⚠️ Chi phí cao hơn (~5x)

### Cách 2: Tạo 1 Lần (Chỉ cho model lớn)
Nếu dùng `gpt-4-turbo` hoặc `gpt-4o`, có thể tạo 1 lần:

```python
# Cần sửa code để không chia chương
# (Hiện tại chưa implement)
```

## 💡 Tips Tiết Kiệm Chi Phí

1. **Dùng model nhỏ cho test**:
   ```python
   # Test với gpt-4o-mini trước
   test_result = create_horror_story(model="gpt-4o-mini")
   
   # Satisfied? Tạo bản final với gpt-4-turbo
   final_result = create_horror_story(model="gpt-4-turbo")
   ```

2. **Giảm temperature cho kết quả ổn định hơn**:
   ```python
   result = generator.generate_horror_story(temperature=0.7)
   # Thay vì 0.85 (ít random hơn = ít cần retry)
   ```

3. **Cache kết quả tốt**:
   - File đã lưu trong `stories/`
   - Dùng lại thay vì tạo mới

## 📈 Ước Tính Chi Phí

### Truyện 10.000 từ (~15.000 tokens output)

| Model | Input Tokens | Output Tokens | Chi phí | Thời gian |
|-------|--------------|---------------|---------|-----------|
| gpt-4-turbo | ~6k | ~15k | $0.51 | 3-5 phút |
| gpt-4o | ~6k | ~15k | $0.26 | 3-5 phút |
| gpt-4o-mini | ~6k | ~15k | $0.01 | 2-4 phút |
| gpt-3.5-turbo-16k | ~6k | ~12k* | $0.02 | 2-3 phút |

*Output giới hạn ở 12k tokens

### Batch 10 Truyện

| Model | Chi phí | Khuyến nghị |
|-------|---------|-------------|
| gpt-4o-mini | ~$0.10 | ⭐⭐⭐ Tốt nhất cho batch |
| gpt-3.5-turbo-16k | ~$0.20 | ⭐⭐ Tốt |
| gpt-4o | ~$2.60 | ⭐ OK nếu cần chất lượng |
| gpt-4-turbo | ~$5.10 | ⚠️ Đắt |

## 🔍 Kiểm Tra Model Hiện Tại

```python
from story_generator import StoryGenerator

gen = StoryGenerator(model="gpt-4-turbo")
print(f"Model: {gen.model}")
print(f"Max tokens: {gen.max_completion_tokens}")
```

## 🆘 Troubleshooting

### Lỗi: "context_length_exceeded"
```
This model's maximum context length is 8192 tokens. 
However, you requested 17197 tokens...
```

**Giải pháp**:
1. ✅ Đổi sang model lớn hơn: `gpt-4-turbo` hoặc `gpt-4o`
2. ✅ Code đã tự động chia chương (không cần sửa gì)
3. ❌ KHÔNG dùng `gpt-4` (context nhỏ)

### Truyện Quá Ngắn
- Tăng `max_tokens` (nếu model cho phép)
- Thêm yêu cầu cụ thể về độ dài trong `custom_requirements`

### Truyện Mất Mạch
- Giảm `temperature` (0.6-0.7)
- Dùng model tốt hơn (`gpt-4-turbo` thay vì `gpt-3.5`)

## 📞 Liên Hệ / Issues

Nếu vẫn gặp vấn đề, kiểm tra:
1. API key hợp lệ
2. Đủ credit trong account OpenAI
3. Model name đúng (xem danh sách trên)

---

**Khuyến nghị cuối cùng**: Dùng **`gpt-4o`** - cân bằng giữa giá và chất lượng! 🎯

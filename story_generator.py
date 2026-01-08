"""
Module để tạo truyện ngắn tự động bằng Google Gemini hoặc OpenAI.
Hỗ trợ nhiều thể loại, bắt đầu với thể loại kinh dị - huyền bí - linh dị Việt Nam.
"""

import json
import os
import time
from typing import Dict, List, Optional
from DiscordMethod import send_discord_message
import google.generativeai as genai
from openai import OpenAI
from config import GEMINI_API_KEY, OPENAI_API_KEY

# Thư mục lưu truyện
STORIES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stories")
os.makedirs(STORIES_DIR, exist_ok=True)


class StoryPrompts:
    """Lưu trữ các prompt cho từng thể loại truyện"""
    
    KINH_DI = {
        "system": """Bạn là một nhà văn chuyên nghiệp về thể loại kinh dị – huyền bí – linh dị Việt Nam.
Phong cách viết của bạn: ma mị, u ám, tinh tế, có tính triết lý nhẹ về "nghiệp", "oan hồn", "ký ức", hoặc "niềm tin".
Bạn lấy cảm hứng từ phong cách Nguyễn Ngọc Ngạn, Stephen King, và Junji Ito.""",
        
        "user_template": """Viết một truyện ngắn thể loại kinh dị – huyền bí – linh dị Việt Nam, độ dài 8.000-12.000 từ tùy theo cốt truyện.

YÊU CẦU CHUNG:
- Không sử dụng yếu tố máu me hay bạo lực quá đà; tập trung vào nỗi sợ tâm linh, sự ám ảnh và cảm giác lạnh gáy.
- Bối cảnh: {boi_canh}
- Giữ nhịp kể chậm rãi, ám ảnh, nhiều chi tiết gợi mở, tạo cảm giác "thật" như có thể xảy ra ngoài đời.
- Nhân vật chính nên có quá khứ hoặc bí mật liên quan đến sự kiện siêu nhiên.
- Cuối truyện phải có KẾT ĐÓNG: nhân vật thoát khỏi ác mộng, sự thật được giải quyết, có thể buồn nhưng phải trọn vẹn và hy vọng.

CẤU TRÚC BẮT BUỘC (tổng 8.000-12.000 từ - điều chỉnh tùy cốt truyện):

1. MỞ ĐẦU (~1.000-1.500 từ):
   - Giới thiệu nhân vật chính, bối cảnh
   - Không khí ban đầu hơi kỳ lạ nhưng chưa rõ ràng

2. PHÁT TRIỂN (~3.000-4.500 từ):
   - Các hiện tượng bất thường dần xuất hiện
   - Giữ tiết tấu chậm, có mô tả âm thanh, ánh sáng, mùi, cảm giác

3. CAO TRÀO (~2.500-4.000 từ):
   - Nhân vật chính bắt đầu đối mặt hoặc tìm ra manh mối về nguồn gốc của hiện tượng

4. CAO TRÀO – ĐỈNH ĐIỂM (~2.000-3.000 từ):
   - Sự thật được hé lộ hoặc nhân vật trải qua sự kiện kinh hoàng

5. KẾT THÚC (~1.000-1.500 từ):
   - Kết đóng: nhân vật thoát khỏi hiểm họa, sự thật được làm sáng tỏ
   - Có thể buồn, cảm động nhưng phải trọn vẹn và để lại cảm giác hy vọng
   - Ác linh được siêu thoát, hoặc nhân vật tìm được cách sống chung với quá khứ

CHỦ ĐỀ: {chu_de}

PHONG CÁCH VIẾT:
- Miêu tả giàu hình ảnh, nhịp chậm, xen lẫn hồi tưởng, nhật ký, hoặc lời kể gián tiếp
- Dùng ngôn ngữ tự nhiên, có tính địa phương, không quá văn hoa
- Mỗi chương/khoảnh khắc nên có ít nhất một chi tiết "ám ảnh" (âm thanh, mùi hương, vật vô tri, ánh mắt, bóng người, lời thì thầm, gió lạnh, v.v.)
- Kể theo NGÔI THỨ NHẤT (dùng "tôi")

TÔNG GIỌNG:
- Ma mị, u ám, tinh tế
- Có tính triết lý nhẹ về "nghiệp", "oan hồn", "ký ức", hoặc "niềm tin"

LƯU Ý ĐẶC BIỆT VỀ FORMAT:
- CHỈ VIẾT NỘI DUNG TRUYỆN THUẦN TÚY - bắt đầu ngay câu chuyện
- KHÔNG viết tiêu đề, tên truyện, giới thiệu thể loại, tên tác giả
- KHÔNG dùng ## MỞ ĐẦU, ## PHẦN 1, ## CHƯƠNG 1, hay bất kỳ tiêu đề phân đoạn nào
- KHÔNG có phần giới thiệu "Đây là truyện về...", "Thể loại: Kinh dị"
- Bắt đầu trực tiếp bằng câu đầu tiên của truyện
- Kể liền mạch từ đầu đến cuối như một văn bản duy nhất

CHỐNG META-COMMENT (NGHIÊM CẤM):
- TUYỆT ĐỐI KHÔNG viết: "Đây là đoạn cao trào", "Twist này thật bất ngờ", "Khoảnh khắc rùng rợn nhất"
- CHỈ KỂ TRUYỆN, KHÔNG bình luận về cấu trúc hoặc cảm xúc của truyện
- Để người đọc tự cảm nhận, ĐỪNG nói cho họ biết phải cảm thấy gì

Viết 8.000-12.000 từ tùy theo cốt truyện (tối thiểu 8.000 từ), KHÔNG tóm tắt. Hãy viết như một tiểu thuyết ngắn thực thụ để đọc thành audio.
Nếu cốt truyện phức tạp, chi tiết nhiều → viết đầy đủ 11.000-12.000 từ.
Nếu cốt truyện gọn, cô đọng → có thể 8.000-9.000 từ nhưng vẫn phải đầy đủ, chi tiết.""",
        
        "themes": [
            'Làng cổ có lời nguyền "không ai được gọi tên người chết".',
            'Bệnh viện bỏ hoang – nơi một y tá vẫn làm việc mỗi đêm.',
            'Căn phòng trọ số 13, nơi gương không bao giờ phản chiếu đúng hình người.',
            'Trường học xây trên nền nghĩa địa.',
            'Bức ảnh gia đình mà gương mặt thứ năm không ai biết là ai.',
            'Người thu âm podcast nghe thấy giọng mình thì thầm trong băng khi không hề nói.',
            'Ngôi nhà cổ bên sông, nơi mỗi đêm trăng rằm có tiếng hát ru ám ảnh.',
            'Chiếc xe buýt cuối cùng, nơi hành khách không bao giờ xuống.',
            'Căn hầm dưới nhà thờ cổ, nơi lưu giữ những lời cầu nguyện ngược.',
            'Cây đa nghìn năm tuổi, nơi mọi người tự tử đều để lại lời nhắn giống hệt nhau.'
        ],
        
        "settings": [
            "làng quê xa xôi miền Bắc",
            "đô thị hiện đại nhưng có khu cũ ẩn chứa bí mật",
            "tu viện bỏ hoang trên núi",
            "ngôi nhà cổ bên sông",
            "trại giam bỏ hoang từ thời chiến tranh",
            "bệnh viện tâm thần cũ",
            "trường học nội trú vùng núi",
            "khu tập thể cũ sắp được phá dỡ",
            "nghĩa trang xe cổ ven đường",
            "hầm trú ẩn thời chiến tranh"
        ]
    }
    
    VA_MAT = {
        "system": """Bạn là nhà văn chuyên viết truyện đô thị hiện đại, thể loại "vả mặt - face slap" với phong cách hài hước, nhẹ nhàng nhưng hả hê.
Bạn giỏi xây dựng tình huống dở khóc dở cười, đối thoại sống động, và khoảnh khắc twist "đỉnh cao" khiến người đọc thỏa mãn.
Phong cách: Hiện đại, gần gũi, hài hước, có "vibe" phim Hàn/Trung về vả mặt văn minh.""",
        
        "user_template": """Viết một truyện ngắn thể loại "vả mặt - face slap" hiện đại, độ dài khoảng 10.000 từ.

CONCEPT CHÍNH:
- Nhân vật chính: Người rất giàu/có địa vị cao (CEO, chủ tịch, nhà đầu tư, người thừa kế, tác giả nổi tiếng...)
- Đang giả làm người bình thường: {vai_tro_gia}
- Bị người khác xem thường, mỉa mai, khinh bỉ vì vẻ ngoài giản dị/nghèo/không nổi bật
- Cuối cùng thân phận thật được tiết lộ → mọi người sững sờ, "vả mặt" cực mạnh
- Nhân vật chính vẫn điềm đạm, không khoe mẽ, thể hiện khí chất đỉnh cao

CẤU TRÚC (~10.000 từ):

1. MỞ ĐẦU (~1.600 từ):
   - Giới thiệu nhân vật chính trong thân phận giả
   - Đơn giản, mộc mạc, hơi lập dị hoặc ít nói
   - Bối cảnh: {boi_canh}
   - Xuất hiện nhân vật phụ đầu tiên - có thái độ coi thường

2. PHÁT TRIỂN (~3.400 từ):
   - Nhiều tình huống bị chê bai, trêu chọc, đánh giá thấp
   - Có những tình huống dở khóc dở cười, hơi "tấu hài"
   - Nhân vật chính vẫn bình thản, đôi khi có phản ứng hài hước
   - Xen lẫn những chi tiết gợi mở về thân phận thật (đồng hồ đắt tiền, cách nói chuyện, kiến thức...)

3. CAO TRÀO (~2.400 từ):
   - Xuất hiện sự kiện/tình huống buộc thân phận thật sắp lộ
   - Có thể là: buổi họp quan trọng, hợp đồng lớn, sự cố, tin tức, người thân xuất hiện...
   - Căng thẳng tăng dần, người đọc mong chờ khoảnh khắc "vả mặt"

4. ĐỈNH ĐIỂM - VẢ MẶT (~2.200 từ):
   - Thân phận thật được tiết lộ một cách bất ngờ nhưng hợp lý
   - Những người từng coi thường giờ phải sững sờ, bối rối, xấu hổ
   - Miêu tả chi tiết phản ứng của từng người
   - Có thể có tình tiết "phản công" nhẹ nhàng nhưng đanh thép

5. KẾT THÚC (~1.000 từ):
   - Nhân vật chính vẫn giữ thái độ khiêm tốn, nở nụ cười nhẹ
   - Để lại câu thoại chất lượng cao, ý nghĩa
    - Kết thúc phải đóng, ấm áp (HAPPY ENDING): không trả thù ác liệt; mâu thuẫn được giải quyết rõ ràng, nhân vật tìm thấy bình yên
   - Thông điệp: "Đừng đánh giá người khác qua bề ngoài"

CHỦ ĐỀ: {chu_de}

PHONG CÁCH VIẾT:
- Hài hước, duyên dáng, tự nhiên
- Văn phong mạng xã hội hiện đại, gần gũi
- Hội thoại sống động, "bắt trend", có năng lượng
- Mô tả chi tiết cảm xúc, biểu cảm nhân vật
- Tạo cảm giác "cool ngầu nhưng tử tế"
- Kể theo NGÔI THỨ NHẤT (dùng "tôi", "mình")

TÔNG GIỌNG:
- Nhẹ nhàng nhưng hả hê
- Châm biếm nhẹ xã hội "chuộng bề ngoài"
- Vẫn giữ tính nhân văn, không cay độc
- "Vả mặt văn minh" - không chửi rủa nhưng cực đã

LƯU Ý ĐẶC BIỆT VỀ FORMAT:
- CHỈ VIẾT NỘI DUNG TRUYỆN THUẦN TÚY - bắt đầu ngay câu chuyện
- KHÔNG viết tiêu đề, tên truyện, giới thiệu thể loại, tên tác giả
- KHÔNG dùng ## MỞ ĐẦU, ## PHẦN 1, ## CHƯƠNG 1, hay bất kỳ tiêu đề phân đoạn nào
- KHÔNG có phần giới thiệu "Đây là truyện về...", "Thể loại: Vả mặt"
- Bắt đầu trực tiếp bằng câu đầu tiên của truyện
- Kể liền mạch từ đầu đến cuối như một văn bản duy nhất
- Nhiều hội thoại, ít miêu tả dài dòng
- Tập trung vào cảm xúc thỏa mãn của người đọc
- Tiết tấu nhanh, không kéo dài

CHỐNG META-COMMENT (NGHIÊM CẤM):
- TUYỆT ĐỐI KHÔNG viết: "Đây là cái vả mặt không thể nào đau hơn", "Khoảnh khắc cao trào", "Twist bất ngờ"
- CHỈ KỂ TRUYỆN, KHÔNG bình luận về mức độ vả mặt hay cảm xúc
- Để người đọc tự cảm nhận sự thỏa mãn, ĐỪNG nói trước

Viết 8.000-12.000 từ tùy theo cốt truyện (tối thiểu 8.000 từ), KHÔNG tóm tắt. Mỗi tình huống cần chi tiết, sinh động, để đọc thành audio.
Nếu có nhiều tình tiết vả mặt hấp dẫn → viết đầy đủ 11.000-12.000 từ.
Nếu cốt truyện gọn nhưng đã đủ hay → có thể 8.000-9.000 từ.""",
        
        "themes": [
            'Anh shipper nghèo bị cô tiểu thư chê bai, hóa ra là chủ tịch công ty cô làm việc.',
            'Thực tập sinh bị sếp mắng ngu, nhưng lại là nhà đầu tư lớn nhất của công ty.',
            'Cô gái giản dị đi mua xe, bị nhân viên bán hàng coi thường, hóa ra là người thừa kế tập đoàn.',
            'Freelancer bị từ chối hợp tác, ai ngờ chính là chủ công ty thiết kế lớn nhất thành phố.',
            'Học sinh nghèo bị bạn học giàu nhạo báng, hóa ra là con của ông chủ trường.',
            'Nhân viên tạp vụ bị đồng nghiệp khinh thường, thật ra là CEO ẩn danh đang khảo sát.',
            'Anh bảo vệ bị cư dân chung cư coi thường, hóa ra là chủ tòa nhà.',
            'Cô phục vụ quán cafe bị khách hàng mắng, thật ra là chủ chuỗi cafe đó.',
            'Sinh viên dạy kèm bị phụ huynh chê, nhưng lại là giáo sư trẻ nhất nước.',
            'Tài xế taxi bị khách xem thường, hoá ra là ông chủ công ty vận tải lớn nhất thành phố.'
        ],
        
        "vai_tro_gia": [
            "shipper giao đồ ăn",
            "thực tập sinh văn phòng",
            "nhân viên bán hàng",
            "freelancer thiết kế",
            "học sinh trường công",
            "nhân viên tạp vụ",
            "bảo vệ tòa nhà",
            "phục vụ quán cafe",
            "sinh viên dạy kèm",
            "tài xế taxi",
            "nhân viên giao hàng",
            "thợ sửa xe",
            "nhân viên kế toán mới vào nghề"
        ],
        
        "settings": [
            "công ty lớn ở trung tâm thành phố",
            "showroom xe hơi sang trọng",
            "trường đại học danh giá",
            "tòa nhà chung cư cao cấp",
            "chuỗi cửa hàng thời trang",
            "khách sạn 5 sao",
            "công ty xuất nhập khẩu",
            "trung tâm thương mại lớn",
            "văn phòng tập đoàn đa quốc gia",
            "buổi gala từ thiện giới thượng lưu"
        ]
    }
    
    RANDOM_MIX = {
        "system": """Bạn là nhà văn đa năng, chuyên kết hợp nhiều thể loại để tạo truyện độc đáo.
Bạn giỏi pha trộn: Hài hước + Tình cảm + Gia đình + Công việc + Làng quê + Đô thị hiện đại.
Có thể có yếu tố siêu nhiên/kinh dị NHƯNG KHÔNG BẮT BUỘC - truyện có thể hoàn toàn đời thường, gần gũi.
Phong cách: Tự nhiên, sinh động, có twist bất ngờ, châm biếm xã hội nhẹ nhàng.""",
        
        "user_template": """Viết truyện ngắn kết hợp nhiều thể loại, độ dài 8.000-12.000 từ tùy theo cốt truyện.

THÔNG TIN TRUYỆN:
- Thể loại chính: {the_loai_chinh}
- Thể loại phụ: {the_loai_phu}
- Nhân vật chính: {nhan_vat}
- Bối cảnh: {boi_canh}
- Mô típ: {mo_tip}

QUY TẮC XUYÊN SUỐT (BẮT BUỘC):
1. TÍNH CÁCH NHÂN VẬT:
   - Nhân vật chính giữ MỘT tính cách duy nhất xuyên suốt
   - Không được thay đổi tính cách trừ khi có biến cố lớn được giải thích rõ ràng
   - Phản ứng phải nhất quán với tính cách đã thiết lập

2. LOGIC THẾ GIỚI TRUYỆN:
   - Mọi yếu tố siêu nhiên PHẢI được giải thích bằng logic của thế giới truyện
   - Quy tắc ma thuật/siêu nhiên một khi đã đặt ra phải tuân thủ đến cuối
   - Không tự nhiên thay đổi "luật vật lý" của thế giới truyện

3. HỒI TƯỞNG:
   - Không hồi tưởng quá dài (tối đa 300 chữ mỗi lần)
   - Phải có dấu hiệu chuyển cảnh rõ ràng (ví dụ: "Tôi nhớ lại...", "Năm đó...")
   - Quay về hiện tại phải mượt mà

4. CHUYỂN CẢNH:
   - KHÔNG nhảy cảnh đột ngột
   - Luôn có dấu hiệu dẫn vào (thời gian trôi qua, di chuyển địa điểm, v.v.)
   - Giữ mạch truyện liền mạch

5. TỈ LỆ THOẠI VÀ MIÊU TẢ:
   - 40% lời thoại – 60% miêu tả
   - Lời thoại ngắn gọn, tự nhiên như ngoài đời
   - Không lạm dụng emoji trong lời thoại
   - Dùng từ lóng vừa phải (không quá hiện đại đến mất tự nhiên)

6. GIỌNG KỂ NHẤT QUÁN:
   - Kể theo NGÔI THỨ NHẤT ("tôi")
   - Giọng kể = chính nhân vật chính
   - Ngữ điệu: châm biếm nhẹ, tỉnh táo, thông minh nhưng đôi lúc ngớ ngẩn hài hước
   - KHÔNG thay đổi giọng điệu đột ngột

7. QUY TẮC VỀ TWIST:
   TWIST phải thỏa 3 điều kiện BẮT BUỘC:
   a) Đã được gợi ý (foreshadowing) ít nhất 2 lần trước đó
   b) Không phá vỡ logic đã xây dựng từ đầu truyện
   c) Liên quan trực tiếp đến chính nhân vật chính (không phải nhân vật phụ)

8. CHỐNG HALLUCINATION (NGHIÊM CẤM):
   TUYỆT ĐỐI KHÔNG viết các đoạn meta như:
   ❌ "Đây là đoạn cao trào"
   ❌ "Tôi bắt đầu chương mới"
   ❌ "Tôi kể hơi dài rồi"
   ❌ "Bạn đang đọc truyện..."
   ❌ "Phần tiếp theo sẽ..."
   ❌ "Đây là cái vả mặt không thể nào đau hơn"
   ❌ "Twist này thật bất ngờ"
   ❌ "Khoảnh khắc cao trào đã đến"
   ❌ Bất kỳ lời bình luận nào VỀ truyện thay vì KỂ truyện
   
   CHỈ KỂ TRUYỆN THUẦN TÚY:
   ✅ Kể hành động, lời thoại, suy nghĩ nhân vật
   ✅ Miêu tả cảnh vật, cảm xúc
   ✅ KHÔNG bao giờ nhắc đến cấu trúc truyện trong nội dung

CẤU TRÚC (8.000-12.000 từ - điều chỉnh tùy cốt truyện):

1. GIỚI THIỆU (~1.200-2.400 từ):
   - Giới thiệu nhân vật chính với tính cách rõ ràng
   - Thiết lập bối cảnh: đời thường (gia đình/công việc/làng quê/tình cảm) HOẶC có yếu tố siêu nhiên (nếu cần)
   - Gợi mở vấn đề/mâu thuẫn chính của truyện

2. PHÁT TRIỂN (~3.000-4.800 từ):
   NẾU TRUYỆN ĐỜI THƯỜNG:
   - Mâu thuẫn/khó khăn trong cuộc sống bắt đầu nổi lên
   - Mối quan hệ giữa nhân vật phát triển phức tạp
   - Nhiều tình huống đời thường sinh động, chân thật
   
   NẾU CÓ YẾU TỐ SIÊU NHIÊN/KỲ BÍ:
   - Sự kiện kỳ lạ đầu tiên xuất hiện
   - Kết hợp yếu tố hài hước hoặc căng thẳng
   - Nhiều tình huống "dở khóc dở cười"

3. CAO TRÀO (~2.000-3.200 từ):
   NẾU TRUYỆN ĐỜI THƯỜNG:
   - Xung đột đạt đỉnh điểm (gia đình/công việc/tình cảm)
   - Nhân vật phải đưa ra quyết định quan trọng
   - Cảm xúc chân thật, tâm lý phức tạp
   
   NẾU CÓ YẾU TỐ ĐẶC BIỆT:
   - Nguy hiểm hoặc bí ẩn leo thang
   - Bắt đầu hé lộ sự thật về tình huống

4. CHUYỂN BIẾN / TIẾT LỘ (~2.000-3.000 từ):
   - Sự thật được phơi bày (thân phận ẩn giấu / hiểu lầm được giải tỏa / bí mật được tiết lộ)
   - Khoảnh khắc "wow" khiến người đọc bất ngờ
   - Có thể có yếu tố "vả mặt" nếu ai đó đã coi thường
   - Hoặc cảm động sâu sắc nếu là truyện tình cảm/gia đình

5. KẾT THÚC (~1.000-1.800 từ):
   - KẾT ĐÓng HAPPY ENDING: vấn đề được giải quyết trọn vẹn, nhân vật tìm được hạnh phúc/bình yên
   - TWIST cuối cùng bất ngờ (nếu có) NHƯNG phải dẫn đến kết thúc tích cực
   - Câu thoại/suy ngẫm đỉnh cao, đầy hy vọng
   - Để lại cảm giác ấm áp, hạnh phúc, trọn vẹn

PHONG CÁCH VIẾT:
- Tự nhiên, gần gũi với đời sống thực tế
- Đôi khi châm biếm xã hội (nhẹ nhàng)
- Giọng văn tự nhiên, dễ nghe
- Nhiều hội thoại sinh động, "bắt trend"
- NẾU có yếu tố siêu nhiên → phải hợp lý, logic, KHÔNG gượng ép
- NẾU KHÔNG có siêu nhiên → tập trung vào cảm xúc, tâm lý, mâu thuẫn con người (ĐÂY LÀ HƯỚNG ƯU TIÊN)
- Có thể hài hước, có thể cảm động, có thể rùng rợn nhẹ - tùy vào thể loại được chọn
- Kể theo NGÔI THỨ NHẤT ("tôi")

LƯU Ý ĐẶC BIỆT VỀ FORMAT:
- CHỈ VIẾT NỘI DUNG TRUYỆN THUẦN TÚY - bắt đầu ngay câu chuyện
- KHÔNG viết tiêu đề, tên truyện, giới thiệu thể loại, tên tác giả
- KHÔNG dùng ## MỞ ĐẦU, ## PHẦN 1, ## CHƯƠNG 1, hay bất kỳ tiêu đề phân đoạn nào
- KHÔNG có phần giới thiệu "Đây là truyện về...", "Thể loại: Random Mix"
- Bắt đầu trực tiếp bằng câu đầu tiên của truyện
- Kể liền mạch từ đầu đến cuối như một văn bản duy nhất

YÊU CẦU ĐẶC BIỆT VỀ NỘI DUNG:
- Twist cuối phải BẤT NGỜ, hợp lý, gây ấn tượng
- Nếu có yếu tố "vả mặt" → phải hả hê
- Nếu có yếu tố kinh dị/siêu nhiên → rùng rợn nhưng không quá đáng sợ
- Nếu có yếu tố hài → tự nhiên, không gượng ép
- Nếu là truyện đời thường → tập trung vào cảm xúc chân thật, mâu thuẫn tâm lý
- Nếu là truyện gia đình/tình cảm → ấm áp nhưng vẫn có chiều sâu
- Kết hợp các thể loại một cách mượt mà, không rời rạc

Viết đầy đủ ~10.000 từ, KHÔNG tóm tắt. Viết để đọc thành audio, liền mạch, tự nhiên.""",
        
        # 150+ THỂ LOẠI CHÍNH
        "the_loai_chinh": [
            # THỂ LOẠI ĐỜI THƯỜNG (ưu tiên cao)
            "Gia đình ấm áp",
            "Hôn nhân sóng gió",
            "Công việc văn phòng",
            "Làng quê bình dị",
            "Tình yêu thanh xuân",
            "Mẹ đơn thân mạnh mẽ",
            "Khởi nghiệp từ zero",
            "Ly hôn tái sinh",
            "Chuyện hàng xóm",
            "Chợ quê buổi sáng",
            "Hài hước gia đình",
            "Office romance",
            "Đời thường gia đình",
            "Học đường thanh xuân",
            "Nghệ thuật đam mê",
            "Y khoa cứu người",
            "Luật pháp công lý",
            "Phá sản đứng dậy",
            "Anh em thất lạc đoàn tụ",
            "Tình yêu tuổi học trò",
            "Hôn nhân giả trở thành thật",
            "Ông chủ nghiêm khắc si tình",
            "Nuôi con một mình",
            "Cha dượng tốt bụng",
            "Mẹ kế hiểu chuyện",
            "Gia đình tái hôn hòa hợp",
            "Sống chung với bố mẹ chồng",
            "Ba thế hệ cùng nhà",
            "Nông thôn lên thành phố",
            "Du học sinh về nước",
            "Chuyên gia nước ngoài về",
            "Bác sĩ trẻ cống hiến",
            "Thương trường đối đầu",
            "Tập đoàn gia tộc",
            "Thừa kế tranh giành",
            "Hôn ước gia tộc",
            "Tổng tài si mê vợ",
            "Tiểu thư bị ruồng bỏ",
            "Lọ lem gặp hoàng tử",
            "Nghịch lưu mà lên",
            
            # THỂ LOẠI VẢ MẶT / LÃNG MẠN
            "Chủ tịch giả nghèo",
            "Lãng mạn ngược đời",
            "Streamer đời thực",
            "Trọng sinh báo thù",
            "Nữ cường kinh doanh",
            "Vả mặt hào môn",
            "Nữ phụ nghịch lên làm nữ chính",
            
            # THỂ LOẠI CỔ TRANG / LỊCH SỬ
            "Cổ trang triều đình",
            "Xuyên không cổ đại",
            "Hoàng hậu trọng sinh",
            "Hoàng tử phế truất",
            "Nữ tướng quân oai phong",
            "Phò mã không muốn làm",
            "Giang hồ nhi nữ",
            "Cao thủ ẩn cư xuống núi",
            "Từ hầu trở thành tướng",
            "Nô tỳ làm hoàng hậu",
            "Thứ nữ vươn lên",
            
            # THỂ LOẠI TRINH THÁM / ĐIỀU TRA (không siêu nhiên)
            "Hành động điều tra",
            "Bí ẩn phòng kín",
            "Trinh thám Dieselpunk",
            
            # THỂ LOẠI KINH DỊ / SIÊU NHIÊN (tỷ lệ thấp hơn)
            "Kinh dị hiện đại",
            "Thực tập sinh bí ẩn",
            "Nhà văn bị ám",
            "Cục điều tra siêu nhiên",
            "Trinh thám u ám",
            "Thần thoại đương đại",
            "Kinh dị tâm lý căng thẳng",
            "Hiện thực huyền ảo",
            "Kinh dị dân gian hiện đại",
            "Kinh dị môi trường",
            "Kinh dị công ty",
            "Siêu nhiên thời xưa tái hiện",
            "Kinh dị cô lập không gian",
            "Kinh dị vũ trụ nhẹ",
            "Kinh dị thể xác tâm lý",
            "Lãng mạn siêu linh",
            "Vòng lặp thời gian căng thẳng",
            "Bí ẩn thực tại thay thế",
            "Âm mưu siêu nhiên",
            "Điều tra giáo phái",
            "Xâm chiếm giấc mơ",
            "Thao túng ký ức",
            "Sống sót tận thế",
            "Tiến hóa hậu nhân loại",
            "Hài hước siêu nhiên",
            "Học thuật đen tối",
            "Lãng mạn Gothic hiện đại",
            "Ly kỳ y khoa bí ẩn",
            "Âm mưu hội kín",
            "Kinh dị khí hậu",
            "Hậu quả đại dịch",
            "Lời nguyền truyền miệng",
            "Ác mộng người nổi tiếng",
            "Bí ẩn câu chuyện có thật",
            "Bí ẩn podcast có thật",
            "Phim tài liệu trở thành sự thật",
            "Reality show chết chóc",
            "Kinh dị found footage",
            "Bi kịch phát sóng trực tiếp",
            "Lời nguyền thử thách nguy hiểm",
            "Ám ảnh qua đồ vật",
            "Xâm chiếm ngôi nhà",
            "Ly kỳ giám sát bí mật",
            "Đánh cắp danh tính",
            "Âm mưu tài chính tối mật",
            "Nghệ thuật ma ám",
            "Giết người trong giấc mơ",
            "Nổi loạn tâm linh",
            "Khủng hoảng danh tính song sinh",
            "Hậu quả thí nghiệm y học",
            "Gián điệp tâm linh",
            "Trinh thám động lực tâm linh",
            "Gánh nặng tiên tri",
            "Quá tải đồng cảm",
            "Đạo đức chuyển linh hồn",
            "Trả thù kiếp sau",
            "Nghiệp báo hiện hình",
            "Thao túng số phận",
            "Viết lại vận mệnh",
            "Lời tiên tri tự thực hiện",
            "Sa đọa nhà tiên tri",
            "Dự đoán tarot thành sự thật",
            "Chiêm tinh học trở thành hiện thực",
            "Ác mộng số học",
            "Phong thủy vũ khí hóa",
            "Nghi lễ sai lầm",
            "Phản tác dụng triệu hồi",
            "Đảo ngược trừ tà",
            "Tự nguyện bị nhập",
            "Gia tài ma ám",
            "Di sản gia tộc bị nguyền rủa",
            "Bí mật dòng máu",
            "Nợ tổ tiên",
            "Vang vọng chấn thương lịch sử",
            "Ma chiến tranh trở về",
            "Lời nguyền thực dân thức tỉnh",
            "Trả thù thổ dân",
            "Văn minh thất lạc tái xuất",
            "Khảo cổ cấm kỵ",
            "Di vật thức tỉnh",
            "Ác mộng bảo tàng",
            "Khu vực cấm thư viện",
            "Bí mật chết chóc lưu trữ",
            "Cha dượng tốt bụng",
            "Mẹ kế hiểu chuyện",
            "Gia đình tái hôn hòa hợp",
            "Sống chung với bố mẹ chồng",
            "Ba thế hệ cùng nhà",
            "Nông thôn lên thành phố",
            "Du học sinh về nước",
            "Chuyên gia nước ngoài về",
            "Bác sĩ trẻ cống hiến"
        ],
        
        # 150+ THỂ LOẠI PHỤ (kết hợp)
        "the_loai_phu": [
            "Hài hước đời thường",
            "Ấm áp tình người",
            "Mâu thuẫn gia đình",
            "Áp lực công việc",
            "Tình yêu tuổi trung niên",
            "Hôn nhân hạnh phúc",
            "Nuôi con nên người",
            "Làng quê nhớ về",
            "Phố thị náo nhiệt",
            "Bạn bè thân thiết",
            "Đồng nghiệp văn phòng",
            "Hài đen",
            "Siêu nhiên học",
            "Khoa học tâm linh",
            "Trừ tà học / Ma học",
            "Phát hiện linh hồn qua nghi lễ cổ",
            "Thế giới ngầm truyền thống",
            "Tổ chức siêu nhiên quốc tế",
            "Hài – twist – ảo thực",
            "Tình cảm – nhận thức – nhân tính",
            "Chính trị / Xã hội ngầm",
            "Trinh thám hiện đại",
            "Giả tưởng đô thị",
            "Khí hậu khoa học viễn tưởng",
            "Kinh dị tâm lý",
            "Châm biếm xã hội",
            "Trượt dòng thực tại",
            "Gothic đương đại",
            "Huyền bí dân gian",
            "Bí ẩn điều tra",
            "Siêu thực",
            "Thư tín thể",
            "Hành trình kỳ lạ",
            "Kinh dị ngắn",
            "Tâm lý chậm rãi",
            "Hài kịch phi lý",
            "Sợ hãi hiện sinh",
            "Vũ trụ thờ ơ",
            "Hư vô vui vẻ",
            "Tận thế lạc quan",
            "Hy vọng kháng chiến",
            "Tối tăm nhẹ",
            "Cao thượng bị lật",
            "Cổ tích méo mó",
            "Thần thoại sa đọa",
            "Truyền thuyết tái giải",
            "Dân gian vũ khí hóa",
            "Mê tín thành sự thật",
            "Truyền thuyết đô thị có thật",
            "Creepypasta hiện thực",
            "Phong cách SCP Foundation",
            "Khám phá Backrooms",
            "Kinh dị không gian trung gian",
            "Kinh dị analog",
            "Suy thoái thực tại",
            "Lỗi nhận thức",
            "Thực tại méo mó",
            "Ký ức tập thể thay đổi",
            "Ký ức bị sai lệch",
            "Thao túng tâm lý siêu nhiên",
            "Người kể chuyện không đáng tin cực đoan",
            "Đa dòng thời gian",
            "Vũ trụ song song thấm vào nhau",
            "Âm mưu đa vũ trụ",
            "Xuyên không huyền ảo",
            "Sự cố di chuyển thời gian",
            "Hệ quả thử nghiệm cổ đại",
            "Dị dạng danh tính",
            "Mất bản sắc",
            "Lời nguyền vô hình",
            "Gánh nặng bất tử",
            "Bẫy tuổi trẻ vĩnh cửu",
            "Kinh dị lão hóa ngược",
            "Thao túng kích thước",
            "Kiểm soát mật độ",
            "Dịch pha",
            "Ngục tù vô hình",
            "Cái giá sức mạnh",
            "Con quỷ tốc độ",
            "Ám ảnh bay",
            "Quá tải thần giao cách cảm",
            "Lời nguyền đọc tâm trí",
            "Tội lỗi thao túng cảm xúc",
            "Nghiện ảo ảnh",
            "Thôi miên phản tác dụng",
            "Xoáy gợi ý",
            "Ma thuật cưỡng chế",
            "Đảo ngược phép mê hoặc",
            "Bi kịch thuốc tình yêu",
            "Lời nguyền hận thù lan tỏa",
            "Sợ hãi vũ khí hóa",
            "Niềm vui độc hại",
            "Buồn bã lây lan",
            "Thực thể tức giận",
            "Ghê tởm hiển hiện",
            "Bất ngờ chết chóc",
            "Tra tấn mong đợi",
            "Bẫy hoài niệm",
            "Ma ân hận",
            "Quỷ tội lỗi",
            "Bóng tối hổ thẹn",
            "Kiêu ngạo sụp đổ",
            "Ghen tị nuốt chửng",
            "Lời nguyền tham lam",
            "Ngục tù lười biếng",
            "Thịnh nộ giải phóng",
            "Ám ảnh dục vọng",
            "Hư vô tham ăn",
            "Gia đình phức tạp",
            "Mối quan hệ rối ren",
            "Bí mật quá khứ",
            "Nghiệp chướng hiện tại",
            "Nhân quả báo ứng",
            "Số phận an bài",
            "Vận mệnh đổi thay",
            "Tình yêu đa giác",
            "Hôn nhân phong kiến",
            "Tranh đấu giai cấp",
            "Mưu mô quyền lực",
            "Phản bội bạn bè",
            "Ân oán gia tộc",
            "Di sản tranh giành",
            "Thế lực đối đầu",
            "Liên minh bất đắc dĩ",
            "Kẻ thù thành bạn",
            "Bạn trở thành thù",
            "Người thứ ba chen ngang",
            "Oan gia ngõ hẹp",
            "Định kiến xã hội",
            "Áp lực gia đình",
            "Thành kiến nghề nghiệp",
            "Khoảng cách tuổi tác",
            "Khác biệt văn hóa",
            "Đối lập tính cách",
            "Hiểu lầm tai hại",
            "Thời gian chữa lành",
            "Tha thứ khó khăn",
            "Hối hận muộn màng",
            "Cơ hội thứ hai",
            "Bắt đầu lại từ đầu"
        ],
        
        # 100+ NHÂN VẬT CHÍNH
        "nhan_vat": [
            "👨‍💼 Chủ tịch giả nghèo: Tự tay đi thực tế để thử lòng người. Vẻ ngoài nhạt nhòa, IQ cao, EQ thấp, phản ứng cực tỉnh.",
            "👮 Điều tra viên tân binh: Thực ra là giám đốc ngầm của Cục Điều Tra Siêu Nhiên, xuống cơ sở kiểm tra.",
            "👻 Streamer bắt ma: Livestream trừ tà, bị khán giả tưởng là giả – cho đến khi thật sự gặp thứ 'không phải người'.",
            "🕵️ Thám tử tư tâm linh: Nhận những vụ án không ai dám nhận, đối mặt với những thế lực vượt khỏi hiểu biết.",
            "🔮 Thầy bói trẻ tuổi: Thừa hưởng năng lực nhìn thấu quá khứ và tương lai, nhưng không thể thay đổi số phận.",
            "🧘 Pháp sư ẩn danh: Sống lẫn trong đời thường, chỉ hiện diện khi có sự kiện siêu nhiên nghiêm trọng.",
            "🧑‍🔬 Nhà khoa học vô thần: Không tin ma, cho đến khi chính thí nghiệm của mình tạo ra hiện tượng vượt ngoài logic.",
            "💅 Kim chủ giản dị: Người giàu có, thích hoà mình vào đám đông. Bị khinh thường cho đến khi lộ thân phận.",
            "🧑‍🎓 Thực tập sinh ngây thơ: Dễ thương, vụng về, nhưng lại là người duy nhất hiểu điều đang xảy ra.",
            "📖 Tác giả bị ám: Mỗi truyện viết ra... lại xảy ra thật. Bắt đầu sợ chính ngòi bút của mình.",
            "🎖️ Cựu chiến binh bí ẩn: Về hưu nhưng vẫn bị ám ảnh bởi quá khứ – và quá khứ không tha.",
            "🌃 Cô gái làm ca đêm ở nhà hàng: Phục vụ khách lạ lúc 3h sáng, nghe những câu chuyện không ai tin.",
            "🕵️ Nhà báo điều tra mạo hiểm: Đào sâu vào những vụ án bị bưng bít, phát hiện sự thật đáng sợ.",
            "🎭 Diễn viên kịch câm: Diễn vai ma quỷ quá chân thật, khiến người xem hoang mang liệu có phải... diễn?",
            "📱 Người quay video phố đêm: Làm nội dung về những góc khuất thành phố, vô tình quay được điều không nên thấy.",
            "👨‍⚕️ Bác sĩ về đêm: Trực cấp cứu những ca 'đặc biệt' – bệnh nhân không hoàn toàn... sống.",
            "🚮 Người thu gom rác ban đêm: Nhặt được những thứ không nên nhặt, biết những điều không nên biết.",
            "🛠️ Thợ mộc miền quê: Nhận đơn hàng làm quan tài đặc biệt, khách hàng không phải người sống.",
            "✈️ Phi công về hưu: Bay chuyến cuối cùng qua vùng 'tam giác quỷ', hành khách biến mất từng người.",
            "🧓 Lão hàng xóm bí ẩn: Sống lâu hơn mọi người nghĩ, biết mọi bí mật trong khu phố.",
            "👪 Cả gia đình chuyển về nhà cũ: Ngôi nhà thừa kế có quá nhiều bí mật dưới tầng hầm.",
            "📻 Kỹ thuật viên âm thanh podcast: Thu âm những câu chuyện ma – rồi phát hiện giọng nói lạ trong file gốc.",
            "🧾 Người quản lý di sản văn hóa: Bảo tồn những di tích cổ, đánh thức những thứ nên để yên.",
            "🧿 Thầy phù thủy/giữ bùa truyền thống: Giữ gìn nghi lễ cổ, nhưng thế hệ trẻ không tin – đến khi quá muộn.",
            "👨‍🏫 Giáo viên dạy ban đêm: Lớp học người lớn, học viên có vẻ... không còn sống.",
            "🎨 Họa sĩ vẽ chân dung: Mỗi bức tranh hoàn thành, chủ nhân lại gặp tai họa kỳ lạ.",
            "🎭 Diễn viên múa rối: Những con rối dần có ý thức riêng, điều khiển ngược lại.",
            "🎪 Chủ rạp xiếc bỏ hoang: Quay lại khai trương, khán giả là những bóng ma từ quá khứ.",
            "🎬 Đạo diễn phim kinh dị: Quay cảnh ma, diễn viên thật sự bị ám.",
            "📸 Nhiếp ảnh gia chụp linh hồn: Camera đặc biệt nhìn thấy cả hai thế giới.",
            "🎤 Ca sĩ hát đám ma: Giọng hát gọi hồn người chết về... nhưng không phải ai cũng muốn về.",
            "🎹 Nhạc sĩ điên: Sáng tác nhạc từ tiếng kêu của linh hồn lạc.",
            "🎸 Guitarist đường phố: Đàn guitar cũ mua từ chợ đồ cũ, mỗi bài hát là một lời nguyền.",
            "🎻 Nghệ sĩ violin thiên tài: Nhạc quá đẹp đến nỗi linh hồn người nghe... không muốn rời.",
            "🥁 Tay trống tại hộp đêm ma: Nhịp trống gọi những thứ không nên gọi.",
            "🎺 Kèn trumpet thời chiến: Chiếc kèn từ chiến tranh, mỗi lần thổi là gọi hồn linh lạc.",
            "🎙️ MC đài phát thanh đêm khuya: Nhận cuộc gọi từ thính giả... đã chết 10 năm.",
            "📺 Biên tập viên truyền hình thực tế: Chương trình quay tại nhà ma, khán giả thấy những gì camera không quay.",
            "🕯️ Thợ làm nến thủ công: Nến làm từ sáp ong cổ, khi thắp lên hiện hình bóng người.",
            "🧵 Thợ may áo cưới: Mỗi chiếc váy may xong đều có dấu vết máu khó giải thích.",
            "📿 Người bán tràng hạt cổ: Chuỗi hạt từ chùa bỏ hoang, đeo vào thấy được kiếp trước.",
            "🖥️ Nhân viên văn phòng ca đêm: Làm việc một mình, nghe tiếng bàn phím từ phòng không người.",
            "📋 Nhân viên lưu trữ hồ sơ cũ: Tìm thấy hồ sơ của chính mình... từ 50 năm trước.",
            "🗄️ Thủ quỹ ngân hàng cũ: Két sắt cổ chứa những bức thư từ người đã khuất.",
            "🖨️ Thợ sửa máy photocopy: Máy in ra những hình ảnh từ quá khứ chưa xảy ra.",
            "📠 Nhân viên fax cũ: Nhận fax từ văn phòng đã đóng cửa 20 năm.",
            "☎️ Tổng đài viên đêm khuya: Nghe những cuộc gọi cầu cứu từ chiều không gian khác.",
            "📞 Thợ sửa điện thoại bàn cũ: Điện thoại cổ chứa tin nhắn từ chủ nhân đã mất.",
            "🕰️ Thợ sửa đồng hồ cổ: Mỗi chiếc đồng hồ sửa xong đều chạy ngược thời gian.",
            "🔔 Người gác chuông nhà thờ: Chuông tự đổ vào nửa đêm, báo hiệu điều gì đó.",
            "🎐 Thợ làm chuông gió: Chuông làm từ xương, kêu lên nghe được lời thì thầm.",
            "📲 Influencer review đồ cũ: Mỗi món đồ có câu chuyện đẫm máu.",
            "📹 Vlogger du lịch địa điểm ma: Quay ở nơi cấm, footage chứa những thứ không thể giải thích.",
            "🎥 TikToker trend ma quái: Làm trend nhảy tại nghĩa địa, những người theo trend... biến mất.",
            "📊 Youtuber phân tích bí ẩn: Đào sâu những vụ án chưa giải quyết, bị theo dõi.",
            "🎞️ Editor video phát hiện frame lạ: Trong footage có những khung hình không ai quay.",
            "🎬 Colorist phim cũ: Phục chế phim cũ, trong đó có cảnh sát nhân thật.",
            "🎚️ Sound designer nghe âm thanh lạ: Thu âm tại địa điểm hoang, nghe thấy lời kêu cứu.",
            "🔊 Foley artist tạo âm thanh: Âm thanh tạo ra... gọi thứ không nên gọi.",
            "🎧 Podcaster solo: Thu một mình trong phòng cách âm, ai đó... đang nghe.",
            "🎼 Nhà soạn nhạc phim kinh dị: Mỗi bản nhạc viết, sự kiện trong phim... xảy ra thật.",
            "🎵 DJ hộp đêm ma: Set nhạc tại club bỏ hoang, khán giả đã chết từ vụ hỏa hoạn.",
            "🔉 Kỹ thuật viên âm thanh sự kiện: Setup âm thanh đám cưới ma, cô dâu chú rể không phản chiếu.",
            "📡 Kỹ thuật viên ăng-ten: Bắt tín hiệu lạ từ không gian sâu thẳm.",
            "🛰️ Kỹ sư vệ tinh: Vệ tinh chụp ảnh Trái Đất, có điều gì đó... nhìn lại.",
            "🔭 Nhà thiên văn nghiệp dư: Quan sát bầu trời đêm, thấy những ngôi sao... không nên thấy.",
            "🌌 Nhà vật lý lượng tử: Thí nghiệm mở cổng sang chiều không gian khác.",
            "⚛️ Nhà hóa học thí nghiệm: Tạo ra chất có ý thức riêng.",
            "🧪 Researcher sinh học: Nuôi cấy tế bào, chúng phát triển thành... điều gì đó.",
            "🔬 Kỹ thuật viên phòng lab đêm: Mẫu vật trong tủ lạnh... không còn chết.",
            "💉 Y tá phòng xét nghiệm: Xét nghiệm máu bệnh nhân, phát hiện DNA không phải người.",
            "💊 Dược sĩ đêm khuya: Bào chế thuốc đặc biệt cho những 'bệnh nhân đặc biệt'.",
            "🏥 Bảo vệ bệnh viện: Tuần tra ban đêm, gặp bệnh nhân không có hồ sơ.",
            "🚑 Nhân viên cấp cứu: Chở bệnh nhân đến bệnh viện không tồn tại.",
            "⚰️ Nhân viên nhà xác: Thi thể di chuyển khi không ai nhìn.",
            "🪦 Người đào mộ: Khai quật mộ cổ, đánh thức thứ không nên đánh thức.",
            "⚱️ Chuyên gia hỏa táng: Tro cốt có ký ức của người chết.",
            "🕯️ Người thắp hương chùa: Thắp hương cho hồn ma vô chủ, họ đòi điều gì đó.",
            "🔮 Thầy bói tarot nghiệp dư: Lá bài dự đoán quá chính xác, khách hàng sợ hãi.",
            "🎴 Nghệ nhân làm bùa: Bùa hộ mệnh bán online, hiệu quả đến đáng sợ.",
            "🧙 Phù thủy thời hiện đại: Phù phép qua app, spell delivery trong 30 phút.",
            "🔯 Nhà nghiên cứu kabbalah: Giải mã ký tự cổ, mở ra cổng địa ngục.",
            "☯️ Thầy phong thủy: Sắp xếp không gian, vô tình mở đường cho linh hồn.",
            "🕉️ Hành giả yoga: Thiền định sâu, linh hồn thoát xác không quay về.",
            "🧘‍♀️ Chuyên gia meditation: Hướng dẫn thiền qua app, học viên rơi vào hôn mê.",
            "💆 Thợ massage năng lượng: Cảm nhận được nghiệp chướng khách hàng.",
            "🌿 Thầy thuốc đông y: Dùng thảo dược cổ, chữa cả bệnh của ma.",
            "🍵 Pha chế trà tâm linh: Mỗi loại trà mở ra một ký ức kiếp trước.",
            "🍜 Đầu bếp món ăn cúng: Nấu đồ cúng cho người chết, họ đến thật sự ăn.",
            "🥘 Food blogger ẩm thực ma quái: Review món ăn ở nhà hàng ma.",
            "🍷 Sommelier rượu cổ: Pha chế rượu từ công thức thế kỷ 18, người uống thấy quá khứ.",
            "☕ Barista quán cà phê đêm: Pha cà phê cho khách lạc lối giữa hai thế giới.",
            "🍰 Thợ làm bánh sinh nhật: Bánh sinh nhật cho người đã khuất.",
            "🧁 Pastry chef ma mị: Bánh ngọt chứa ký ức của người làm ra nó.",
            "🎂 Wedding cake designer: Bánh cưới cho đám cưới ma.",
            "👔 Tổng giám đốc trẻ tuổi: Thừa kế công ty gia đình, đối đầu với thế lực cũ.",
            "💼 Nhân viên văn phòng bình thường: Bị kéo vào âm mưu công ty.",
            "👨‍⚖️ Luật sư tân binh: Nhận vụ án đầu tiên khó nhằn.",
            "👩‍🏫 Giáo viên tiểu học: Phát hiện học sinh có hoàn cảnh đặc biệt.",
            "🏃 Vận động viên chấn thương: Tìm cách trở lại đỉnh cao.",
            "🎭 Diễn viên quần chúng: Mơ ước một vai chính.",
            "📝 Biên kịch trẻ: Viết kịch bản dựa trên trải nghiệm thực.",
            "🎬 Đạo diễn độc lập: Làm phim với kinh phí eo hẹp.",
            "📚 Thủ thư thầm lặng: Giữ bí mật của những độc giả.",
            "☕ Chủ quán cà phê nhỏ: Lắng nghe tâm sự khách hàng.",
            "🍜 Chủ quán phở gia truyền: Giữ gìn công thức truyền thống.",
            "🚕 Tài xế taxi đêm: Chở những vị khách đặc biệt.",
            "🚌 Lái xe buýt tuyến xa: Gặp đủ thứ người trên đường.",
            "✈️ Tiếp viên hàng không: Du lịch khắp nơi nhưng cô đơn.",
            "🏨 Nhân viên lễ tân khách sạn: Chứng kiến nhiều câu chuyện.",
            "🔧 Thợ sửa ống nước: Vô tình biết bí mật gia đình.",
            "🔨 Thợ xây nhà: Xây từng viên gạch ước mơ.",
            "👨‍🌾 Nông dân trồng trọt: Chống chọi với thiên tai.",
            "🎣 Ngư dân đánh cá: Sinh kế trên biển cả.",
            "👨‍🍳 Đầu bếp nhà hàng: Nấu từ tâm hồn.",
            "🧑‍🔧 Thợ máy garage: Sửa xe và sửa lòng người.",
            "📦 Nhân viên giao hàng: Chạy khắp thành phố mọi lúc.",
            "🏪 Chủ tiệm tạp hóa: Nuôi sống gia đình từ cửa hàng nhỏ.",
            "💇 Thợ cắt tóc: Nghe tâm sự khách hàng mỗi ngày.",
            "💅 Thợ làm nail: Người nhập cư mưu sinh.",
            "🧵 Thợ may: Khâu vá cuộc đời.",
            "👞 Thợ đánh giày: Nghề nhỏ nhưng tự trọng.",
            "🔑 Thợ khóa: Mở khóa nhà và lòng người.",
            "🪴 Người bán hoa: Mang niềm vui đến cho người khác.",
            "📖 Gia sư dạy kèm: Giúp học sinh vượt khó.",
            "🏋️ Huấn luyện viên gym: Thay đổi thể hình và tâm hồn.",
            "🧘 Giáo viên yoga: Tìm bình an trong tâm trí.",
            "🎸 Nhạc sĩ nghiệp dư: Làm nhạc vì đam mê.",
            "📷 Thợ ảnh cưới: Lưu giữ khoảnh khắc hạnh phúc.",
            "🎨 Họa sĩ vẽ chân dung: Vẽ linh hồn người.",
            "📝 Nhà văn tự do: Viết để sống và sống để viết.",
            "🎙️ Phóng viên địa phương: Đưa tin cho cộng đồng.",
            "📹 Youtuber nhỏ: Làm nội dung với ít view.",
            "🎮 Pro gamer: Sống bằng nghề chơi game.",
            "🏡 Môi giới bất động sản: Bán nhà và câu chuyện.",
            "📊 Kế toán công ty nhỏ: Giữ sổ sách cho sếp.",
            "👨‍💻 IT freelancer: Code thuê ở nhà.",
            "🎓 Sinh viên nghèo: Học hành vất vả tự nuôi mình.",
            "🧑‍🎨 Designer đồ họa: Thiết kế cho khách hàng nhỏ.",
            "📱 Sửa chữa điện thoại: Dịch vụ ở chợ.",
            "🚗 Tài xế taxi truyền thống: chở khách khắp thành phố.",
            "🏭 Công nhân nhà máy: Làm ca kíp vất vả."
        ],
        
        # 100+ BỐI CẢNH
        "boi_canh": [
            "🏢 Cục điều tra siêu nhiên - nơi khoa học và tâm linh gặp nhau",
            "🏢 Trung tâm nghiên cứu tâm linh truyền thống - nơi các già làng và pháp sư gặp nhau",
            "🏙️ Quán cà phê hoạt động sau nửa đêm - khách hàng đặc biệt",
            "🏙️ Khách sạn chỉ mở lúc 3h sáng - nơi 'những người đặc biệt' nghỉ ngơi",
            "📡 Kênh livestream bắt ma - 100k người xem mỗi đêm",
            "📡 Group Facebook 'Chuyện Lạ Thật' - 2 triệu thành viên",
            "🏫 Học viện nghiên cứu siêu hình học - nơi thử nghiệm giữa khoa học và ma thuật",
            "🏫 Viện nghiên cứu văn hoá dân gian - lưu giữ huyền thoại địa phương",
            "🧩 Hội kín nghiên cứu cõi âm - giới nhà giàu chơi bùa",
            "🧩 Hiệp hội nghiên cứu cõi âm - nơi tổ chức nghi lễ và lưu giữ câu chuyện",
            "✈️ Sân bay quốc tế ban đêm",
            "🏭 Khu công nghiệp hoang vắng",
            "⛏️ Mỏ than bỏ hoang",
            "🏝️ Hòn đảo du lịch bị bỏ hoang",
            "🏘️ Khu chung cư 90s",
            "🛣️ Đường cao tốc ban đêm",
            "🐟 Làng chài ven biển",
            "🚉 Nhà ga bỏ hoang",
            "🏔️ Khu trượt tuyết vắng vẻ",
            "🏛️ Bảo tàng đồ cổ",
            "🚇 Hệ thống tàu điện ngầm cũ",
            "🏚️ Hẻm nhỏ trong thành phố",
            "🎡 Công viên giải trí bỏ hoang",
            "🎢 Lunapark đóng cửa từ thập niên 80",
            "🎠 Rạp xiếc lưu động cuối cùng",
            "🎪 Sở thú đêm - động vật lạ",
            "🦁 Thủy cung ngầm bí mật",
            "🐘 Safari park ma ám",
            "🏟️ Sân vận động Olympic cũ",
            "🏀 Nhà thi đấu bóng rổ hoang phế",
            "⚽ Sân bóng đêm khuya",
            "🏊 Bể bơi trong nhà bị bỏ quên",
            "🎾 Sân tennis vắng người",
            "🏓 Câu lạc bộ thể thao ngầm",
            "🎯 Trường bắn cũ",
            "🎱 Quán bi-a 24/7",
            "🎰 Casino hầm ngầm",
            "🃏 Phòng poker bí mật",
            "📚 Câu lạc bộ kể chuyện ma địa phương",
            "🕹️ Arcade retro những năm 90",
            "📺 Quán cà phê chiếu phim cũ",
            "🏚️ Nhà kho bỏ hoang",
            "🖨️ Văn phòng in ấn đêm khuya",
            "📠 Trung tâm tổng đài cũ",
            "📞 Trạm điện thoại công cộng cuối cùng",
            "📻 Đài phát thanh FM bỏ hoang",
            "📺 Trường quay truyền hình cũ",
            "🎬 Xưởng phim kinh dị thập niên 70",
            "🎥 Studio chụp ảnh vintage",
            "📸 Phòng tối phim analog",
            "🎞️ Rạp chiếu phim độc lập",
            "🎭 Nhà hát opera bỏ hoang",
            "🎪 Sân khấu kịch nghiệp dư",
            "🎨 Phòng tranh gallery tối",
            "🖼️ Xưởng điêu khắc bỏ hoang",
            "🗿 Bảo tàng sáp đóng cửa",
            "🏺 Kho đồ cổ ngầm",
            "📚 Thư viện cấm sách",
            "📖 Hiệu sách cũ mở đêm",
            "✍️ Nhà xuất bản bí ẩn",
            "🖊️ Xưởng in cổ",
            "📰 Toà soạn báo đêm khuya",
            "📋 Văn phòng thám tử tư",
            "🔍 Phòng điều tra tư nhân",
            "🕵️ Trụ sở cơ quan tình báo ngầm",
            "🚓 Đồn cảnh sát bỏ hoang",
            "🚔 Trạm kiểm soát giao thông đêm",
            "🚨 Trung tâm 911 ma ám",
            "🚑 Trạm cấp cứu cũ",
            "🚒 Trạm cứu hỏa bỏ hoang",
            "🏥 Bệnh viện tâm thần đóng cửa",
            "💊 Hiệu thuốc đêm khuya",
            "⚕️ Phòng khám tư nhân bí ẩn",
            "🧬 Phòng lab di truyền ngầm",
            "🔬 Viện nghiên cứu sinh học cấm",
            "🧪 Nhà máy hóa chất bỏ hoang",
            "⚗️ Xưởng luyện kim cổ",
            "🔭 Đài thiên văn trên núi",
            "🛰️ Trạm radar bỏ hoang",
            "📡 Trạm phát sóng bí ẩn",
            "🗼 Tháp truyền hình cũ",
            "🌉 Cầu treo bỏ hoang",
            "🛤️ Đường ray xe lửa cũ",
            "🚂 Ga tàu hỏa thời Pháp",
            "🚊 Tuyến tàu điện cổ",
            "🚝 Tàu monorail ngừng hoạt động",
            "🚁 Bãi đáp trực thăng bỏ hoang",
            "🛩️ Sân bay nhỏ hoang phế",
            "✈️ Nhà chứa máy bay cũ",
            "🚀 Bệ phóng tên lửa bỏ hoang",
            "🛸 Khu vực UFO bí ẩn",
            "🌠 Observatory ngầm",
            "🌌 Planetarium đóng cửa",
            "⭐ Lab vật lý thiên văn",
            "🔭 Trạm quan sát vũ trụ sâu",
            "🌍 Trung tâm khí tượng bỏ hoang",
            "🌊 Trạm nghiên cứu đại dương sâu",
            "🏖️ Resort biển bỏ hoang",
            "🏝️ Đảo riêng của tỷ phú kỳ lạ",
            "⛱️ Bãi biển cấm vào ban đêm",
            "🏄 Surf club hoang phế",
            "⛵ Bến du thuyền ma",
            "🚤 Xưởng đóng tàu cũ",
            "🏢 Tòa nhà văn phòng hiện đại",
            "🏬 Trung tâm thương mại đông đúc",
            "🏪 Chợ truyền thống buổi sáng",
            "🏘️ Khu phố cũ Hà Nội",
            "🌃 Phố đi bộ Sài Gòn đêm",
            "🏡 Làng quê yên bình",
            "🌾 Cánh đồng lúa mùa gặt",
            "⛰️ Vùng núi cao biên giới",
            "🏝️ Đảo xa bờ",
            "🌊 Làng chài ven biển miền Trung",
            "🏔️ Thị trấn miền núi phía Bắc",
            "🏙️ Thành phố lớn nhộn nhịp",
            "🏘️ Khu chung cư bình dân",
            "🏠 Biệt thự khu nhà giàu",
            "🏚️ Nhà cấp 4 ngoại ô",
            "🏫 Trường học nội trú",
            "🎓 Đại học danh tiếng",
            "🏥 Bệnh viện đa khoa",
            "⛪ Nhà thờ cổ",
            "🕌 Chùa Phật giáo",
            "🏛️ Di tích lịch sử",
            "🎭 Nhà hát lớn",
            "🎬 Phim trường",
            "📚 Thư viện quốc gia",
            "🏛️ Bảo tàng mỹ thuật",
            "🏟️ Sân vận động quốc gia",
            "⚽ Sân bóng cộng đồng",
            "🏊 Bể bơi công cộng",
            "🎡 Công viên giải trí",
            "🌳 Công viên trung tâm",
            "🌲 Rừng quốc gia",
            "🏞️ Thác nước thác Bản Giốc",
            "🗻 Đèo Hải Vân",
            "🌅 Vịnh Hạ Long",
            "🏖️ Biển Nha Trang",
            "🏜️ Đồi cát Mũi Né",
            "☕ Quán cà phê vỉa hè",
            "🍜 Quán phở đông khách",
            "🍺 Quán nhậu ven đường",
            "🏨 Khách sạn mini",
            "🏩 Nhà nghỉ giá rẻ",
            "🚉 Ga tàu hỏa",
            "🚌 Bến xe khách liên tỉnh",
            "✈️ Sân bay Tân Sơn Nhất",
            "🚇 Tàu điện Cát Linh - Hà Đông",
            "🌉 Cầu Long Biên",
            "🏛️ Hồ Gươm buổi sáng",
            "🌆 Phố cổ Hội An",
            "🏯 Hoàng thành Huế",
            "🏰 Thành cổ Quảng Trị"
        ],
        
        # 150+ MÔ TÍP CỐT TRUYỆN
        "mo_tip": [
            # VẢ MẶT - THÂN PHẬN
            "Vả mặt cực mạnh: Nhân vật bị coi thường → lộ thân phận → mọi người sững sờ",
            "Thử lòng / kiểm tra nhân phẩm: Giả nghèo – thử lòng – vả mặt – twist nhân quả",
            "Tỷ phú giả nghèo bị khinh rẻ, lộ thân phận sau khi bị đuổi",
            "Con nhà giàu giả nghèo đi học, bị bạn bè coi thường rồi vả mặt",
            "Chủ tịch giả làm nhân viên, kiểm tra lòng người rồi sa thải hàng loạt",
            "Thiên tài y học bị gọi là庸医, chữa bệnh cho quan chức rồi vả mặt",
            "Võ sĩ ẩn danh bị thách đấu, một chiêu hạ gục tất cả",
            "Đầu bếp huyền thoại bị chê nấu dở, thắng cuộc thi quốc tế vả mặt",
            "Họa sĩ vô danh bị chê tranh rác, tác phẩm bán giá triệu đô",
            "Ca sĩ giấu mặt bị chê giọng tệ, lên sân khấu gây sốt toàn cầu",
            
            # TRỌNG SINH - HỒI QUÍ
            "Trọng sinh về quá khứ sửa sai lầm, thay đổi vận mệnh",
            "Hồi quy 10 năm trước, tránh thảm họa và đổi đời",
            "Trọng sinh thành kẻ thù của mình, nhìn sự việc từ góc độ khác",
            "Về lại ngày định mệnh, cứu người thân khỏi tai nạn",
            "Trọng sinh với ký ức kiếp trước, trả thù kẻ hại mình",
            "Hồi quy về tuổi thơ, dùng kiến thức tương lai làm giàu",
            "Trọng sinh thành nhân vật phụ trong cuốn tiểu thuyết từng đọc",
            "Về lại mốc thời gian trước khi gia đình phá sản",
            "Trọng sinh thành chính mình ở vũ trụ song song",
            "Hồi quy về thời điểm chọn sai nghề nghiệp",
            
            # NỮ CƯỜNG - NĂNG LỰC
            "Nữ chủ tịch lật đổ âm mưu trong hội đồng quản trị",
            "Nữ bác sĩ tài ba vạch trần vụ bê bối y khoa",
            "Nữ luật sư đấu tranh cho công lý trong vụ án lớn",
            "Nữ hacker thiên tài trừng trị tội phạm mạng",
            "Nữ võ sĩ giành championship thế giới",
            "Nữ doanh nhân khởi nghiệp từ con số 0 thành tỷ phú",
            "Nữ cảnh sát phá đường dây tội phạm nguy hiểm",
            "Nữ nhà khoa học phát minh đột phá cứu nhân loại",
            "Nữ chính trị gia đấu tranh chống tham nhũng",
            "Nữ streamer xây dựng đế chế truyền thông",
            
            # ĐỜI THƯỜNG HIỆN ĐẠI
            "Bị bạn thân phản bội tình cảm, phát hiện sự thật đau lòng",
            "Mất việc vào lúc khó khăn, tìm được cơ hội đổi đời",
            "Gia đình tan vỡ vì hiểu lầm, hàn gắn sau nhiều năm",
            "Tình yêu tuổi học trò gặp lại sau 10 năm",
            "Startup thất bại phá sản, học cách đứng dậy từ đổ vỡ",
            "Mẹ đơn thân nuôi con vượt khó khăn thành công",
            "Anh em từ mặt nhau vì gia sản, hối hận muộn màng",
            "Bệnh nan y, tìm ý nghĩa sống trong thời gian cuối",
            "Chênh lệch địa vị xã hội trong tình yêu",
            "Sống ảo trên mạng, đối mặt thực tại tàn khốc",
            "Nợ nần chồng chất, tìm cách thoát khỏi vòng xoáy",
            "Bị bắt nạt ở công sở, đấu tranh bảo vệ quyền lợi",
            "Giấc mơ nghệ sĩ gặp thực tại cuộc sống",
            "Du học xa nhà, học cách trưởng thành một mình",
            "Hôn nhân trên danh nghĩa, dần nảy sinh tình thật",
            
            # CỔ TRANG - TRIỀU ĐÌNH
            "Tiểu thư gia tộc bị vu oan, trả thù rửa hận",
            "Hoàng tử thất sủng tìm cách giành lại ngôi vị",
            "Nữ tướng quân cải trang nam giới bảo vệ biên cương",
            "Thái giám nắm quyền hành, đấu đá triều đình",
            "Công chúa giả chết trốn hôn ước, tìm tự do",
            "Thiên kim tiểu thư xuống dân gian trải nghiệm",
            "Thứ nữ bị ruồng bỏ, vươn lên thành chánh thất",
            "Phụ mã bị ép gả vào hoàng gia, mưu cầu thoát thân",
            "Tình đối đầu nghĩa giữa giang hồ và triều đình",
            "Nữ thương nhân làm ăn phát đạt trong xã hội phong kiến",
            
            # KINH DOANH - QUYỀN MƯU
            "Thâu tóm công ty đối thủ bằng kế hoạch hoàn hảo",
            "Rò rỉ bí mật thương mại, tìm nội gián trong tập đoàn",
            "Chiến tranh giá cả giữa hai ông lớn ngành hàng",
            "Bị đối tác phản bội trong thương vụ tỷ đô",
            "Thừa kế gia nghiệp với núi nợ và âm mưu tranh giành",
            "Khởi nghiệp đối đầu với công ty gia đình",
            "Vạch trần gian lận tài chính trong tập đoàn",
            "Cổ đông chiến tranh quyền lực trong đại hội",
            "Sáp nhập công ty, xử lý xung đột văn hóa doanh nghiệp",
            "Phá sản do khủng hoảng kinh tế, tìm cách tái khởi nghiệp",
            
            # HỌC ĐƯỜNG - THANH XUÂN
            "Học sinh cá biệt bị hiểu lầm, chứng minh tài năng",
            "Tình tréo ngoe tam giác giữa ba bạn thân",
            "Thi đại học căng thẳng, áp lực từ gia đình",
            "Câu lạc bộ trường học tranh giành tài trợ và danh tiếng",
            "Bắt nạt học đường và hành trình vượt qua",
            "Thầy giáo trẻ thay đổi lớp học cá biệt",
            "Tình cảm thầy trò vượt qua định kiến xã hội",
            "Đại diện trường thi quốc gia, gánh áp lực",
            "Scandal bí mật giữa các học sinh ưu tú",
            "Đoàn kết lớp học đối đầu với bất công",
            
            # GIA ĐÌNH - TÌNH CẢM
            "Mẹ chồng nàng dâu xung đột, tìm cách hòa giải",
            "Anh em tranh giành tài sản gia đình",
            "Con cái không hiểu cha mẹ, hối hận khi quá muộn",
            "Nuôi dưỡng con nuôi, phát hiện bí mật gia đình",
            "Ly hôn giành quyền nuôi con, đấu tranh pháp lý",
            "Gia đình đa thế hệ sống chung, xung đột giá trị",
            "Bí mật thân thế được tiết lộ sau nhiều năm",
            "Đoàn tụ gia đình sau chiến tranh ly tán",
            "Chăm sóc cha mẹ già, cân bằng giữa nghĩa vụ và cuộc sống",
            "Anh chị em ruột xa cách, hàn gắn tình cảm",
            
            # NGHỆ THUẬT - ĐAM MÊ
            "Nghệ sĩ vô danh kiên trì đam mê dù khó khăn",
            "Tài năng trẻ bị ghen ghét trong giới nghệ thuật",
            "Đạo diễn quay phim bom tấn vượt mọi khó khăn",
            "Họa sĩ nghèo bán tranh nuôi gia đình",
            "Nhạc sĩ sáng tác hit từ trải nghiệm đau thương",
            "Vũ công ballet vượt qua chấn thương trở lại sân khấu",
            "Nhà văn viết tự truyện phơi bày tội ác xã hội",
            "Nhiếp ảnh gia ghi lại khoảnh khắc lịch sử",
            "Diễn viên kịch tranh vai chính trong vở diễn quan trọng",
            "Nghệ nhân gìn giữ nghề truyền thống sắp mai một",
            
            # XÃ HỘI - HIỆN THỰC
            "Nhà báo điều tra vạch trần tham nhũng quyền lực",
            "Luật sư bào chữa cho người vô tội bị kết án oan",
            "Bác sĩ điều trị bệnh nhân nghèo miễn phí",
            "Giáo viên dạy học ở vùng sâu vùng xa khó khăn",
            "Công nhân đấu tranh cho quyền lợi chính đáng",
            "Người vô gia cư tìm lại ý nghĩa cuộc sống",
            "Cựu tù nhân tái hòa nhập xã hội gặp nhiều khó khăn",
            "Người khuyết tật vượt lên số phận, thành công rực rỡ",
            "Di dân bất hợp pháp tìm cơ hội sống tốt hơn",
            "Nạn nhân bạo lực gia đình tìm cách thoát khỏi",
            
            # SIÊU NHIÊN - MA THUẬT (giữ lại các mô típ hay)
            "Bắt ma giả gặp ma thật: Livestream dàn dựng nhưng lại gặp hàng thật",
            "Tâm linh và đời thường va chạm: đồ vật, tín hiệu đời thường bộc lộ điều kỳ lạ",
            "Hài đen xã hội: Cười ra nước mắt – người thật đáng sợ hơn ma",
            "Niềm tin và nỗi sợ: Người không tin ma lại gặp nhiều nhất",
            "Thế giới gương phản chiếu thực tại",
            "Lời nguyền lan truyền qua mạng xã hội",
            "Âm thanh cũ mở ra ký ức bị chôn vùi",
            "Tin nhắn ẩn trong nhật ký cũ",
            "Vật kỷ niệm dẫn tới ký ức tập thể",
            "Truyền thuyết lan truyền gây hiện tượng",
            "Bức hình thay đổi theo thời gian",
            "Giọng nói trên radio chỉ nghe được khi mưa",
            "Bản thu âm bị hỏng hé lộ sự thật",
            "Sự kiện lịch sử tái diễn",
            "Thư tuyệt mật mở ra thảm họa",
            "Bức tượng dường như sống dậy",
            "Vòng lặp thời gian 24 giờ không thoát ra",
            "Ngày lặp lại mãi mãi như phim Groundhog",
            "Thức dậy mỗi ngày ở thân xác người khác",
            "Ký ức bị xóa sạch mỗi đêm",
            "Giấc mơ thành hiện thực đáng sợ",
            "Ác mộng tập thể lan truyền",
            "Vũ trụ song song va chạm nhau",
            "Dòng thời gian tách nhánh vì quyết định",
            "Hiệu ứng cánh bướm cực đoan",
            "Phản ứng dây chuyền lời nguyền",
            "Hiệu ứng domino siêu nhiên",
            "Tiếng vọng từ quá khứ cảnh báo",
            "Ký ức Deja vu là dấu hiệu nguy hiểm",
            "Linh cảm về tương lai đen tối",
            "Lời tiên tri tự thực hiện"
        ]
    }

    # New trending genres (not included in RANDOM_MIX by default)
    TRONG_SINH = {
        "system": """Bạn là nhà văn chuyên viết thể loại 'trọng sinh' (rebirth / transmigration).
Phong cách: xúc cảm mạnh, xây dựng hố và trả hố rõ ràng, cốt truyện có tính chiến lược, nhân vật chính thông minh, có quyết tâm thay đổi số mệnh.
Yêu cầu đặc biệt: Kết thúc đóng — kẻ ác phải bị trừng trị, người lương thiện được báo đáp rõ ràng, không để kết mở.""",

        "user_template": """Viết một truyện ~8.000-12.000 từ thể loại 'trọng sinh'.

YÊU CẦU CHUNG:
- Nhân vật chính: được trọng sinh (về trước hoặc sang thân khác) với ký ức đời trước.
- Mạch truyện: từ thấp -> cao -> trả thù/giải quyết -> kết thúc rõ ràng.
- Kết thúc phải đóng: kẻ ác bị trừng trị một cách hợp lý, người lương thiện được báo đáp, không để câu chuyện kết mở.

CẤU TRÚC ĐỀ XUẤT:
1. MỞ ĐẦU: giới thiệu hoàn cảnh đời trước, lý do bị hại/đứng sau bi kịch.
2. TRỌNG SINH: miêu tả khoảnh khắc trọng sinh, nhận thức người đọc về thay đổi.
3. LẬP KẾ HOẠCH: nhân vật tích lũy lực lượng, tố chất, bí kíp.
4. THỰC THI: bắt đầu lật ngược thế cờ, đối đầu kẻ thù.
5. TRẢ THÙ & BÙ ĐẮP: công lý được thực thi, kẻ ác chịu quả báo, người tốt được báo đáp.
6. KẾT THÚC: kết luận rõ ràng, hậu quả minh bạch, thông điệp về công lý/nhân quả.

BỐI CẢNH: {boi_canh}
CHỦ ĐỀ: {chu_de}
""",

        "themes": [
            "Trọng sinh thành con nuôi của gia tộc quyền lực để lật đổ nội bộ.",
            "Trọng sinh về làm nô tỳ, dùng trí nhớ kiếp trước thay đổi vận mệnh.",
            "Trọng sinh thành người thừa kế bị gạt ra ngoài để trả thù những kẻ phản bội.",
            "Trọng sinh trong thân phận kẻ thù để phá tan từ bên trong.",
            "Trọng sinh với ký ức đầy đủ, lập kế hoạch công phu lật kèo kẻ ác."
        ],

        "settings": [
            "triều đại giả tưởng/tiền hiện đại",
            "tập đoàn phong kiến/gia tộc quyền lực",
            "thành phố hiện đại với hậu trường chính trị",
            "thế giới giả tưởng có hệ thống tu luyện",
            "làng xã cổ với mưu mô quyền lực"
        ]
    }

    NU_CUONG = {
        "system": """Bạn là nhà văn giỏi viết thể loại 'nữ cường' (female-protagonist / strong female lead).
Phong cách: nhân vật chính là nữ mạnh mẽ, chủ động, có năng lực, nhân vật phản diện bị trừng trị, người lương thiện được báo đáp. Kết thúc phải rõ ràng, cảm giác thỏa mãn cho độc giả.
Lưu ý: tránh văn hóa bạo lực quá mức; trừng trị có thể là mặt trận xã hội, pháp luật hoặc đảo ngược thế cờ tâm lý.""",

        "user_template": """Viết một truyện ~8.000-12.000 từ thể loại 'nữ cường'.

YÊU CẦU CHUNG:
- Nhân vật chính: nữ, năng lực rõ ràng (thông minh, kỹ năng, địa vị hoặc sức mạnh nội tâm).
- Cốt truyện: khởi đầu khó khăn -> phát triển năng lực/quan hệ -> đối đầu -> chiến thắng có hậu.
- Kết thúc đóng: kẻ ác bị trừng trị (bằng công lý, xấu hổ, mất cơ hội), người tốt được báo đáp (thăng tiến, hạnh phúc rõ rệt).

CẤU TRÚC ĐỀ XUẤT:
1. MỞ ĐẦU: thiết lập áp lực mà nhân vật nữ phải chịu.
2. PHÁT TRIỂN: nhân vật tích luỹ năng lực, tạo đồng minh.
3. CAO TRÀO: đối đầu trực tiếp với phản diện.
4. ĐẢO NGƯỢC: người xấu bị lật tẩy, mất thế; người chính đạt công lý.
5. KẾT THÚC: kết thúc rõ ràng, khung hậu công bằng, người chính được báo đáp.

BỐI CẢNH: {boi_canh}
CHỦ ĐỀ: {chu_de}
""",

        "themes": [
            "Nữ lãnh đạo trẻ lật đổ âm mưu trong công ty cha cô.",
            "Nữ võ giả vượt qua định kiến, giành lại công lý cho gia tộc.",
            "Nữ hacker dùng kỹ năng đòi lại công bằng cho người thân bị hại.",
            "Nữ bác sĩ vạch trần âm mưu y tế, cứu lấy bệnh nhân và danh dự nghề nghiệp.",
            "Nữ doanh nhân khuất phục đối thủ bằng trí tuệ và đạo đức.",
        ],

        "settings": [
            "thành phố hiện đại, môi trường doanh nghiệp",
            "hệ thống tu luyện giả tưởng có luật lệ nghiêm khắc",
            "bệnh viện/viện nghiên cứu",
            "thế giới học đường/giảng đường có quyền lực ngầm",
            "môi trường startup/công nghệ cạnh tranh"
        ]
    }

    XUYEN_KHONG = {
        "system": """Bạn là nhà văn giỏi viết thể loại 'xuyên không' (trở về quá khứ hoặc xuyên vào thân xác khác).
Phong cách: lãng mạn kết hợp phiêu lưu, có yếu tố thời gian và hậu quả quyết định số phận. Kết thúc nên rõ ràng, công lý được thực thi hoặc số phận thay đổi theo hướng tích cực.
Yêu cầu: giữ logic thời gian, hạn chế paradox không cần thiết, và kết thúc đóng.""",

        "user_template": """Viết một truyện ~6.000-12.000 từ thể loại 'xuyên không'.

YÊU CẦU CHUNG:
- Nhân vật chính: xuyên về quá khứ hoặc sang thân xác khác, giữ ký ức kiếp trước.
- Mạch truyện: khám phá quá khứ -> tận dụng kiến thức hiện đại -> thay đổi số phận -> kết thúc rõ ràng.

BỐI CẢNH: {boi_canh}
CHỦ ĐỀ: {chu_de}
""",

        "themes": [
            "Xuyên về làm con trai của gia tộc quyền lực để thay đổi lịch sử gia tộc.",
            "Xuyên về thời phong kiến với ký ức hiện đại, dùng trí tuệ thay đổi vận mệnh.",
            "Xuyên vào thân xác người khác trong tương lai để ngăn một thảm kịch.",
            "Xuyên thành kẻ yếu để rèn luyện và thay đổi kết cục.",
            "Xuyên đến thế giới song song để sửa sai cho kiếp trước."
        ],

        "settings": [
            "làng quê thời cũ",
            "triều đại giả tưởng",
            "thành phố hiện đại nhưng có yếu tố lịch sử",
            "hệ thống tu luyện giả tưởng",
            "gia tộc quyền lực" 
        ]
    }

    TRINH_THAM = {
        "system": """Bạn là nhà văn trinh thám chuyên nghiệp.
Phong cách: chặt chẽ, logic, nhiều hint/foreshadowing, mô tả cảnh điều tra, kết thúc phải giải thích được mọi mảnh ghép (closed ending).
Yêu cầu: không để kẽ hở logic, nêu rõ kết luận và cách chứng minh tội ác.
""",

        "user_template": """Viết một truyện trinh thám ~6.000-10.000 từ.

YÊU CẦU CHUNG:
- Đặt vụ án/âm mưu rõ ràng ngay từ đầu.
- Dàn nhân chứng, manh mối, giả thuyết.
- Kết luận hợp lý, có chứng cứ buộc tội kẻ ác và giải thích động cơ.

BỐI CẢNH: {boi_canh}
CHỦ ĐỀ: {chu_de}
""",

        "themes": [
            "Vụ án mạng trong khu chung cư - manh mối chồng chéo.",
            "Bí ẩn chiếc nhẫn cũ liên quan đến tội phạm quá khứ.",
            "Người mất tích để lại thư bí ẩn, dần hé lộ mạng lưới tội phạm.",
            "Vụ lừa đảo công nghệ cao che giấu động cơ cá nhân.",
            "Một series trộm kỳ lạ liên quan tới một tổ chức ngầm."
        ],

        "settings": [
            "khu chung cư thành phố",
            "thành phố cảng",
            "khách sạn sang trọng",
            "quán cà phê nghệ sĩ",
            "văn phòng công ty" 
        ]
    }

    HE_THONG = {
        "system": """Bạn là nhà văn viết thể loại 'hệ thống' (system/skill-based worlds).
Phong cách: mô tả rõ ràng luật chơi, hệ thống (skill, level, reward), nhân vật tiến hóa theo hệ thống, kết thúc rõ ràng.
Yêu cầu: giữ consistency của hệ thống, giải thích cách nhân vật thắng kẻ ác bằng lợi thế hệ thống.
""",

        "user_template": """Viết một truyện ~6.000-10.000 từ thể loại 'hệ thống'.

YÊU CẦU CHUNG:
- Mô tả hệ thống (level, skill, reward) rõ ràng.
- Nhân vật tận dụng hệ thống để phát triển và đối phó phản diện.
- Kết thúc đóng, kẻ ác bị trừng trị theo logic hệ thống.

BỐI CẢNH: {boi_canh}
CHỦ ĐỀ: {chu_de}
""",

        "themes": [
            "Người chơi nhận được giao diện hệ thống giúp tăng sức mạnh từng bước.",
            "Hệ thống đổi vận mệnh: điểm tích lũy đổi lấy quyền lực.",
            "Nhân vật bị ép buộc vào thử thách hệ thống để sinh tồn.",
            "Hệ thống cho phép 'reset' nhưng có chi phí lớn.",
            "Cạnh tranh giữa người có hệ thống và kẻ dùng mưu mô."
        ],

        "settings": [
            "thế giới game-like/ảo thực",
            "thành phố có luật lệ hệ thống",
            "học viện đào tạo kỹ năng",
            "sàn đấu mạo hiểm",
            "thế giới tu luyện có UI hệ thống"
        ]
    }

    VAO_THE_GIOI_GAME = {
        "system": """Bạn là nhà văn viết thể loại 'vào thế giới game' (GameLit / Isekai to game world).
Phong cách: mô tả mechanics trò chơi, cảm giác nhập vai, tiến trình rõ ràng, kết thúc thỏa mãn.
Yêu cầu: giữ quy tắc game, giải thích thắng/thua bằng mechanics, kết thúc rõ ràng.
""",

        "user_template": """Viết một truyện ~6.000-12.000 từ thể loại 'vào thế giới game'.

YÊU CẦU CHUNG:
- Nhân vật chính bị đưa vào thế giới game hoặc bị trap vào game.
- Mô tả mechanics, nhiệm vụ, party, boss.
- Kết thúc đóng: hoàn thành nhiệm vụ lớn, kẻ ác chịu quả báo.

BỐI CẢNH: {boi_canh}
CHỦ ĐỀ: {chu_de}
""",

        "themes": [
            "Người chơi bị mắc kẹt trong MMORPG sống động, phải hoàn thành cốt truyện để về nhà.",
            "Thế giới game reset nhưng nhân vật giữ kỹ năng, tìm cách phá vòng lặp.",
            "Party gồm nhân vật đời thực với kỹ năng khác nhau cùng hợp tác đánh boss.",
            "NPC tự ý thức, giúp hoặc phản bội người chơi.",
            "Cạnh tranh giữa guild để chiếm quyền kiểm soát thế giới." 
        ],

        "settings": [
            "thế giới huyền ảo",
            "đấu trường cổ",
            "thành phố huyền thoại",
            "vùng đất thần thoại",
            "phòng nghiên cứu bí ẩn" 
        ]
    }


class StoryGenerator:
    """Class chính để tạo truyện tự động bằng Google Gemini hoặc OpenAI"""
    
    def __init__(self, model: Optional[str] = None):
        """
        Khởi tạo StoryGenerator với Gemini
        
        Args:
            model: Tên model Gemini (mặc định "gemini-1.5-pro")
            gemini_api_key: API key cho Gemini (nếu None, đọc từ biến môi trường GEMINI_API_KEY)
        """

        # Lấy API key từ tham số hoặc biến môi trường
        gem_key = GEMINI_API_KEY
        openai_key = OPENAI_API_KEY
        
        if not gem_key:
            raise RuntimeError(
                "❌ GEMINI_API_KEY is required! "
                "Please set GEMINI_API_KEY environment variable or pass gemini_api_key parameter."
            )
        
        # Cấu hình Gemini
        try:
            genai.configure(api_key=gem_key)
            self.model = model or "gemini-1.5-pro"
            self._gemini = genai
            send_discord_message(f"✅ Gemini client configured (model={self.model})")
        except Exception as e:
            raise RuntimeError(f"Failed to configure Gemini client: {e}")
        
        # Cấu hình OpenAI
        try:
            self._openai = OpenAI(api_key=openai_key)
            send_discord_message(f"✅ OpenAI client configured")
        except Exception as e:
            send_discord_message(f"⚠️ OpenAI init failed: {e}")
            self._openai = None
        
        # Thiết lập max_completion_tokens
        self.max_completion_tokens = 40000  # Tăng lên để hỗ trợ truyện 10k-12k từ

        send_discord_message(f"✅ Khởi tạo với model: {self.model} (max_tokens: {self.max_completion_tokens})")

        # Load lịch sử truyện đã tạo
        self.history_file = os.path.join(STORIES_DIR, "generation_history.json")
        self.load_history()
    
    def load_history(self):
        """Load lịch sử truyện đã tạo"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []
        else:
            self.history = []
    
    def save_history(self, entry: Dict):
        """Lưu entry vào lịch sử"""
        self.history.append(entry)
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            send_discord_message(f"⚠️ Không lưu được lịch sử: {e}")
    
    def generate_horror_story(
        self, 
        theme: Optional[str] = None,
        setting: Optional[str] = None,
        custom_requirements: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.8
    ) -> Dict[str, any]:
        """
        Tạo truyện kinh dị - huyền bí - linh dị Việt Nam
        
        Args:
            theme: Chủ đề (nếu None sẽ chọn ngẫu nhiên từ danh sách)
            setting: Bối cảnh (nếu None sẽ chọn ngẫu nhiên)
            custom_requirements: Yêu cầu tùy chỉnh thêm
            max_tokens: Số token tối đa (16000 cho truyện 10k từ)
            temperature: Độ sáng tạo (0.0-1.0, cao = sáng tạo hơn)
        
        Returns:
            Dict chứa thông tin truyện: {
                'title': str,
                'content': str,
                'theme': str,
                'setting': str,
                'word_count': int,
                'generation_time': float,
                'file_path': str,
                'metadata': dict
            }
        """
        import random
        
        # Chọn theme và setting ngẫu nhiên nếu không được cung cấp
        if theme is None:
            theme = random.choice(StoryPrompts.KINH_DI['themes'])
        
        if setting is None:
            setting = random.choice(StoryPrompts.KINH_DI['settings'])
        
        send_discord_message("📝 Bắt đầu tạo truyện kinh dị...")
        send_discord_message(f"   Chủ đề: {theme}")
        send_discord_message(f"   Bối cảnh: {setting}")
        
        # Tạo prompt
        user_prompt = StoryPrompts.KINH_DI['user_template'].format(
            chu_de=theme,
            boi_canh=setting
        )
        
        if custom_requirements:
            user_prompt += f"\n\nYÊU CẦU BỔ SUNG:\n{custom_requirements}"
        
        # Tự động điều chỉnh max_tokens nếu không được cung cấp
        if max_tokens is None:
            max_tokens = self.max_completion_tokens
        
        send_discord_message(f"⚙️  Sử dụng max_tokens: {max_tokens}")
        
        # Single-shot Gemini generation
        start_time = time.time()

        system_prompt = (
            "Bạn là nhà văn chuyên nghiệp về thể loại kinh dị – huyền bí – linh dị Việt Nam.\n\n"
            "PHONG CÁCH VIẾT BẮT BUỘC:\n"
            "- Kể theo NGÔI THỨ NHẤT (dùng \"tôi\", \"mình\") - KHÔNG dùng tên nhân vật từ xa\n"
            "- Ma mị, u ám, tinh tế - KHÔNG dùng máu me hay bạo lực quá đà\n"
            "- Tập trung vào nỗi sợ tâm linh, sự ám ảnh, cảm giác lạnh gáy\n"
            "- Nhịp độ CHẬM, miêu tả từng chi tiết nhỏ (âm thanh, mùi, ánh sáng, cảm xúc)\n"
            "- Ngôn ngữ Việt tự nhiên, có thể có thổ ngữ địa phương\n"
            "- KHÔNG DÙNG tiêu đề ## hay phần, chỉ viết nội dung truyện thuần túy\n\n"
            "YÊU CẦU VỀ GIỌNG VĂN VÀ TỪ VỰNG:\n"
            "- Viết bằng tiếng Việt đời thường, ngôn ngữ giản dị, gần gũi như kể chuyện với bạn bè.\n"
            "- Tuyệt đối tránh dùng từ mượn tiếng Anh hoặc tiếng lóng Anh (ví dụ: 'cool', 'vibe', 'ok', ...). Nếu cần, thay bằng từ thuần Việt tương đương.\n\n"
            "CHI TIẾT KHÍ QUYỂN:\n"
            "- Âm thanh: tiếng gió, cửa kêu, thì thầm, bước chân...\n"
            "- Mùi hương: hoa, ẩm mốc, nhang, đất...\n"
            "- Ánh sáng: bóng đổ, trăng, đèn leo lét...\n"
            "- Cảm giác: lạnh, da gà, sợ hãi...\n\n"
            "YẾU TỐ BẮT BUỘC:\n"
            "- Nhân vật (TÔI) liên hệ với siêu nhiên (quá khứ kỳ lạ)\n"
            "- Triết lý về nghiệp, oan hồn, ký ức\n"
            "- Kết thúc phải đóng và có hướng tích cực (HAPPY ENDING): mọi mâu thuẫn được giải quyết rõ ràng; nếu có twist thì twist dẫn đến kết thúc hy vọng/ấm áp"
        )

        # YÊU CẦU VỀ ĐỊNH DẠNG OUTPUT: model phải trả về TIÊU ĐỀ cùng lúc với NỘI DUNG
        # Format mong muốn (bắt buộc):
        # Dòng đầu: TIÊU ĐỀ: <tiêu đề truyện>
        # (1 dòng trống)
        # Tiếp theo: toàn bộ nội dung truyện thuần túy (bắt đầu ngay câu đầu tiên của truyện)
        # Không chèn thêm tiêu đề hay phân đoạn khác trong phần nội dung.
        system_prompt += (
            "\n\nOUTPUT FORMAT (bắt buộc):\n"
            "- Dòng đầu: TIÊU ĐỀ: <tiêu đề truyện>\n"
            "- Bỏ một dòng trống, rồi bắt đầu phần nội dung truyện thuần túy.\n"
            "- KHÔNG in thêm tiêu đề hay phân đoạn khác.\n"
        )
        try:
            send_discord_message("🤖 (Gemini) Generating full story in single-shot...")
            prompt = system_prompt + "\n\n" + user_prompt

            # Sử dụng GenerativeModel API của Gemini
            model = self._gemini.GenerativeModel(self.model)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens
                )
            )
            
            raw_text = response.text.strip()
            title, story_content = self._parse_title_and_content(raw_text, fallback=f"Truyện: {theme}")
            generation_time = time.time() - start_time
            word_count = len(story_content.split())

            file_path = self._save_story(title, story_content, theme, setting)

            metadata = {
                'model': self.model,
                'theme': theme,
                'setting': setting,
                'word_count': word_count,
                'generation_time': generation_time,
                'timestamp': time.time(),
                'custom_requirements': custom_requirements,
                'tokens_used': None,
                'chapters': []
            }

            history_entry = {
                'title': title,
                'file_path': file_path,
                'metadata': metadata
            }
            self.save_history(history_entry)

            result = {
                'title': title,
                'content': story_content,
                'theme': theme,
                'setting': setting,
                'word_count': word_count,
                'generation_time': generation_time,
                'file_path': file_path,
                'metadata': metadata
            }
            
            send_discord_message(f"💾 Đã lưu truyện: {file_path}")
            send_discord_message(f"✅ Hoàn tất tạo truyện! Độ dài: {word_count:,} từ | Thời gian: {generation_time:.1f}s")

            return result

        except Exception as e:
            send_discord_message(f"❌ Lỗi khi tạo truyện: {e}")
            raise
    
    def generate_face_slap_story(
        self,
        theme: Optional[str] = None,
        vai_tro_gia: Optional[str] = None,
        setting: Optional[str] = None,
        custom_requirements: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.85
    ) -> Dict[str, any]:
        """
        Tạo truyện "vả mặt - face slap" hiện đại
        
        Args:
            theme: Chủ đề (nếu None sẽ chọn ngẫu nhiên)
            vai_tro_gia: Vai trò giả của nhân vật chính (nếu None sẽ chọn ngẫu nhiên)
            setting: Bối cảnh (nếu None sẽ chọn ngẫu nhiên)
            custom_requirements: Yêu cầu tùy chỉnh thêm
            max_tokens: Số token tối đa
            temperature: Độ sáng tạo (0.0-1.0)
        
        Returns:
            Dict chứa thông tin truyện
        """
        import random
        
        # Chọn ngẫu nhiên nếu không được cung cấp
        if theme is None:
            theme = random.choice(StoryPrompts.VA_MAT['themes'])
        
        if vai_tro_gia is None:
            vai_tro_gia = random.choice(StoryPrompts.VA_MAT['vai_tro_gia'])
        
        if setting is None:
            setting = random.choice(StoryPrompts.VA_MAT['settings'])
        
        send_discord_message("📝 Bắt đầu tạo truyện vả mặt...")
        send_discord_message(f"   Chủ đề: {theme}")
        send_discord_message(f"   Vai trò giả: {vai_tro_gia}")
        send_discord_message(f"   Bối cảnh: {setting}")
        
        # Tạo prompt
        user_prompt = StoryPrompts.VA_MAT['user_template'].format(
            chu_de=theme,
            vai_tro_gia=vai_tro_gia,
            boi_canh=setting
        )
        
        if custom_requirements:
            user_prompt += f"\n\nYÊU CẦU BỔ SUNG:\n{custom_requirements}"
        
        # Tự động điều chỉnh max_tokens nếu không được cung cấp
        if max_tokens is None:
            max_tokens = self.max_completion_tokens
        
        send_discord_message(f"⚙️  Sử dụng max_tokens: {max_tokens}")
        
        # Single-shot generation: build system + user prompt and call model once.
        start_time = time.time()

        system_prompt = (
            "Bạn là nhà văn chuyên viết truyện \"vả mặt\" hiện đại.\n\n"
            "PHONG CÁCH VIẾT BẮT BUỘC:\n"
            "- Kể theo NGÔI THỨ NHẤT (dùng \"tôi\")\n"
            "- Hài hước, nhẹ nhàng, hiện đại\n"
            "- Nhiều HỘI THOẠI, ít miêu tả dài dòng\n"
            "- Văn phong mạng xã hội, gần gũi, \"bắt trend\"\n"
            "- KHÔNG DÙNG tiêu đề ## hay phần, chỉ viết nội dung truyện thuần túy\n\n"
            "TÔNG GIỌNG:\n"
            "- Nhẹ nhàng nhưng hả hê\n"
            "- \"Vả mặt văn minh\" - không cay độc\n"
            "- Cool ngầu nhưng tử tế\n"
            "- Tập trung cảm giác thỏa mãn của người đọc"
            "\nYÊU CẦU VỀ GIỌNG VĂN VÀ TỪ VỰNG:\n"
            "- Viết bằng tiếng Việt đời thường, gần gũi, như kể chuyện với bạn bè.\n"
            "- Tuyệt đối không dùng từ mượn tiếng Anh hoặc tiếng lóng Anh (ví dụ: 'cool', 'vibe', 'lol', 'ok', ...). Nếu muốn, dùng từ tiếng Việt tương đương.\n"
        )

        # YÊU CẦU VỀ ĐỊNH DẠNG OUTPUT: trả về tiêu đề cùng lúc với nội dung
        system_prompt += (
            "\n\nOUTPUT FORMAT (bắt buộc):\n"
            "- Dòng đầu: TIÊU ĐỀ: <tiêu đề truyện>\n"
            "- Bỏ một dòng trống, rồi bắt đầu phần nội dung truyện thuần túy.\n"
            "- KHÔNG in thêm tiêu đề hay phân đoạn khác.\n"
        )
        try:
            send_discord_message("🤖 (Gemini) Generating face-slap story in single-shot...")
            prompt = system_prompt + "\n\n" + user_prompt

            # Sử dụng GenerativeModel API của Gemini
            model = self._gemini.GenerativeModel(self.model)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens
                )
            )
            
            raw_text = response.text.strip()
            title, story_content = self._parse_title_and_content(raw_text, fallback=theme)
            generation_time = time.time() - start_time
            word_count = len(story_content.split())

            file_path = self._save_story_face_slap(title, story_content, theme, vai_tro_gia, setting)

            metadata = {
                'model': self.model,
                'genre': 'va_mat',
                'theme': theme,
                'vai_tro_gia': vai_tro_gia,
                'setting': setting,
                'word_count': word_count,
                'generation_time': generation_time,
                'timestamp': time.time(),
                'custom_requirements': custom_requirements,
                'tokens_used': None,
                'chapters': []
            }

            history_entry = {
                'title': title,
                'file_path': file_path,
                'metadata': metadata
            }
            self.save_history(history_entry)

            result = {
                'title': title,
                'content': story_content,
                'theme': theme,
                'vai_tro_gia': vai_tro_gia,
                'setting': setting,
                'word_count': word_count,
                'generation_time': generation_time,
                'file_path': file_path,
                'metadata': metadata
            }

            send_discord_message(f"💾 Đã lưu truyện: {file_path}")
            send_discord_message(f"✅ Hoàn tất tạo truyện vả mặt! Độ dài: {word_count:,} từ | Thời gian: {generation_time:.1f}s")

            return result

        except Exception as e:
            send_discord_message(f"❌ Lỗi khi tạo truyện: {e}")
            raise
    
    def generate_rebirth_story(
        self,
        theme: Optional[str] = None,
        setting: Optional[str] = None,
        custom_requirements: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.85
    ) -> Dict[str, any]:
        """Tạo truyện thể loại 'trọng sinh' (rebirth).

        Kết thúc đóng: kẻ ác bị trừng trị, người tốt được báo đáp rõ ràng.
        Không thêm thể loại này vào RANDOM_MIX.
        """
        import random
        if theme is None:
            theme = random.choice(StoryPrompts.TRONG_SINH['themes'])
        if setting is None:
            setting = random.choice(StoryPrompts.TRONG_SINH['settings'])

        send_discord_message("📝 Bắt đầu tạo truyện trọng sinh...")
        send_discord_message(f"   Chủ đề: {theme}")
        send_discord_message(f"   Bối cảnh: {setting}")

        user_prompt = StoryPrompts.TRONG_SINH['user_template'].format(
            chu_de=theme,
            boi_canh=setting
        )
        if custom_requirements:
            user_prompt += f"\n\nYÊU CẦU BỔ SUNG:\n{custom_requirements}"

        if max_tokens is None:
            max_tokens = self.max_completion_tokens

        start_time = time.time()
        system_prompt = StoryPrompts.TRONG_SINH['system'] + "\n\nOUTPUT FORMAT (bắt buộc):\n- Dòng đầu: TIÊU ĐỀ: <tiêu đề truyện>\n- Bỏ một dòng trống, rồi bắt đầu phần nội dung truyện thuần túy."

        try:
            send_discord_message("🤖 (Gemini) Generating rebirth story in single-shot...")
            prompt = system_prompt + "\n\n" + user_prompt
            model = self._gemini.GenerativeModel(self.model)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens
                )
            )
            raw_text = response.text.strip()
            title, story_content = self._parse_title_and_content(raw_text, fallback=theme)
            generation_time = time.time() - start_time
            word_count = len(story_content.split())
            file_path = self._save_story(title, story_content, theme, setting)

            metadata = {'model': self.model, 'genre': 'trong_sinh', 'theme': theme, 'setting': setting, 'word_count': word_count, 'generation_time': generation_time, 'timestamp': time.time(), 'custom_requirements': custom_requirements}
            self.save_history({'title': title, 'file_path': file_path, 'metadata': metadata})

            send_discord_message(f"💾 Đã lưu truyện: {file_path}")
            send_discord_message(f"✅ Hoàn tất tạo truyện trọng sinh! Độ dài: {word_count:,} từ | Thời gian: {generation_time:.1f}s")

            return {'title': title, 'content': story_content, 'theme': theme, 'setting': setting, 'word_count': word_count, 'generation_time': generation_time, 'file_path': file_path, 'metadata': metadata}
        except Exception as e:
            send_discord_message(f"❌ Lỗi khi tạo truyện trọng sinh: {e}")
            raise

    def generate_nu_cuong_story(
        self,
        theme: Optional[str] = None,
        setting: Optional[str] = None,
        custom_requirements: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.85
    ) -> Dict[str, any]:
        """Tạo truyện thể loại 'nữ cường' (female strong lead).

        Kết thúc đóng: kẻ ác bị trừng trị, người tốt được báo đáp.
        """
        import random
        if theme is None:
            theme = random.choice(StoryPrompts.NU_CUONG['themes'])
        if setting is None:
            setting = random.choice(StoryPrompts.NU_CUONG['settings'])

        send_discord_message("📝 Bắt đầu tạo truyện nữ cường...")
        send_discord_message(f"   Chủ đề: {theme}")
        send_discord_message(f"   Bối cảnh: {setting}")

        user_prompt = StoryPrompts.NU_CUONG['user_template'].format(
            chu_de=theme,
            boi_canh=setting
        )
        if custom_requirements:
            user_prompt += f"\n\nYÊU CẦU BỔ SUNG:\n{custom_requirements}"

        if max_tokens is None:
            max_tokens = self.max_completion_tokens

        start_time = time.time()
        system_prompt = StoryPrompts.NU_CUONG['system'] + "\n\nOUTPUT FORMAT (bắt buộc):\n- Dòng đầu: TIÊU ĐỀ: <tiêu đề truyện>\n- Bỏ một dòng trống, rồi bắt đầu phần nội dung truyện thuần túy."

        try:
            send_discord_message("🤖 (Gemini) Generating female-hero story in single-shot...")
            prompt = system_prompt + "\n\n" + user_prompt
            model = self._gemini.GenerativeModel(self.model)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens
                )
            )
            raw_text = response.text.strip()
            title, story_content = self._parse_title_and_content(raw_text, fallback=theme)
            generation_time = time.time() - start_time
            word_count = len(story_content.split())
            file_path = self._save_story(title, story_content, theme, setting)

            metadata = {'model': self.model, 'genre': 'nu_cuong', 'theme': theme, 'setting': setting, 'word_count': word_count, 'generation_time': generation_time, 'timestamp': time.time(), 'custom_requirements': custom_requirements}
            self.save_history({'title': title, 'file_path': file_path, 'metadata': metadata})

            send_discord_message(f"💾 Đã lưu truyện: {file_path}")
            send_discord_message(f"✅ Hoàn tất tạo truyện nữ cường! Độ dài: {word_count:,} từ | Thời gian: {generation_time:.1f}s")

            return {'title': title, 'content': story_content, 'theme': theme, 'setting': setting, 'word_count': word_count, 'generation_time': generation_time, 'file_path': file_path, 'metadata': metadata}
        except Exception as e:
            send_discord_message(f"❌ Lỗi khi tạo truyện nữ cường: {e}")
            raise

    def generate_xuyen_khong_story(
        self,
        theme: Optional[str] = None,
        setting: Optional[str] = None,
        custom_requirements: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.85
    ) -> Dict[str, any]:
        """Tạo truyện thể loại 'xuyên không'. Kết thúc đóng."""
        import random
        if theme is None:
            theme = random.choice(StoryPrompts.XUYEN_KHONG['themes'])
        if setting is None:
            setting = random.choice(StoryPrompts.XUYEN_KHONG['settings'])

        send_discord_message("📝 Bắt đầu tạo truyện xuyên không...")
        send_discord_message(f"   Chủ đề: {theme}")
        send_discord_message(f"   Bối cảnh: {setting}")

        user_prompt = StoryPrompts.XUYEN_KHONG['user_template'].format(
            chu_de=theme,
            boi_canh=setting
        )
        if custom_requirements:
            user_prompt += f"\n\nYÊU CẦU BỔ SUNG:\n{custom_requirements}"

        if max_tokens is None:
            max_tokens = self.max_completion_tokens

        start_time = time.time()
        system_prompt = StoryPrompts.XUYEN_KHONG['system'] + "\n\nOUTPUT FORMAT (bắt buộc):\n- Dòng đầu: TIÊU ĐỀ: <tiêu đề truyện>\n- Bỏ một dòng trống, rồi bắt đầu phần nội dung truyện thuần túy."

        try:
            send_discord_message("🤖 (Gemini) Generating xuyen khong story in single-shot...")
            prompt = system_prompt + "\n\n" + user_prompt
            model = self._gemini.GenerativeModel(self.model)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens
                )
            )
            raw_text = response.text.strip()
            title, story_content = self._parse_title_and_content(raw_text, fallback=theme)
            generation_time = time.time() - start_time
            word_count = len(story_content.split())
            file_path = self._save_story(title, story_content, theme, setting)

            metadata = {'model': self.model, 'genre': 'xuyen_khong', 'theme': theme, 'setting': setting, 'word_count': word_count, 'generation_time': generation_time, 'timestamp': time.time(), 'custom_requirements': custom_requirements}
            self.save_history({'title': title, 'file_path': file_path, 'metadata': metadata})

            send_discord_message(f"💾 Đã lưu truyện: {file_path}")
            send_discord_message(f"✅ Hoàn tất tạo truyện xuyên không! Độ dài: {word_count:,} từ | Thời gian: {generation_time:.1f}s")

            return {'title': title, 'content': story_content, 'theme': theme, 'setting': setting, 'word_count': word_count, 'generation_time': generation_time, 'file_path': file_path, 'metadata': metadata}
        except Exception as e:
            send_discord_message(f"❌ Lỗi khi tạo truyện xuyên không: {e}")
            raise

    def generate_trinh_tham_story(
        self,
        theme: Optional[str] = None,
        setting: Optional[str] = None,
        custom_requirements: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.75
    ) -> Dict[str, any]:
        """Tạo truyện thể loại 'trinh thám' (closed ending)."""
        import random
        if theme is None:
            theme = random.choice(StoryPrompts.TRINH_THAM['themes'])
        if setting is None:
            setting = random.choice(StoryPrompts.TRINH_THAM['settings'])

        send_discord_message("📝 Bắt đầu tạo truyện trinh thám...")
        send_discord_message(f"   Chủ đề: {theme}")
        send_discord_message(f"   Bối cảnh: {setting}")

        user_prompt = StoryPrompts.TRINH_THAM['user_template'].format(
            chu_de=theme,
            boi_canh=setting
        )
        if custom_requirements:
            user_prompt += f"\n\nYÊU CẦU BỔ SUNG:\n{custom_requirements}"

        if max_tokens is None:
            max_tokens = self.max_completion_tokens

        start_time = time.time()
        system_prompt = StoryPrompts.TRINH_THAM['system'] + "\n\nOUTPUT FORMAT (bắt buộc):\n- Dòng đầu: TIÊU ĐỀ: <tiêu đề truyện>\n- Bỏ một dòng trống, rồi bắt đầu phần nội dung truyện thuần túy."

        try:
            send_discord_message("🤖 (Gemini) Generating trinh tham story in single-shot...")
            prompt = system_prompt + "\n\n" + user_prompt
            model = self._gemini.GenerativeModel(self.model)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens
                )
            )
            raw_text = response.text.strip()
            title, story_content = self._parse_title_and_content(raw_text, fallback=theme)
            generation_time = time.time() - start_time
            word_count = len(story_content.split())
            file_path = self._save_story(title, story_content, theme, setting)

            metadata = {'model': self.model, 'genre': 'trinh_tham', 'theme': theme, 'setting': setting, 'word_count': word_count, 'generation_time': generation_time, 'timestamp': time.time(), 'custom_requirements': custom_requirements}
            self.save_history({'title': title, 'file_path': file_path, 'metadata': metadata})

            send_discord_message(f"💾 Đã lưu truyện: {file_path}")
            send_discord_message(f"✅ Hoàn tất tạo truyện trinh thám! Độ dài: {word_count:,} từ | Thời gian: {generation_time:.1f}s")

            return {'title': title, 'content': story_content, 'theme': theme, 'setting': setting, 'word_count': word_count, 'generation_time': generation_time, 'file_path': file_path, 'metadata': metadata}
        except Exception as e:
            send_discord_message(f"❌ Lỗi khi tạo truyện trinh thám: {e}")
            raise

    def generate_he_thong_story(
        self,
        theme: Optional[str] = None,
        setting: Optional[str] = None,
        custom_requirements: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.85
    ) -> Dict[str, any]:
        """Tạo truyện thể loại 'hệ thống'."""
        import random
        if theme is None:
            theme = random.choice(StoryPrompts.HE_THONG['themes'])
        if setting is None:
            setting = random.choice(StoryPrompts.HE_THONG['settings'])

        send_discord_message("📝 Bắt đầu tạo truyện hệ thống...")
        send_discord_message(f"   Chủ đề: {theme}")
        send_discord_message(f"   Bối cảnh: {setting}")

        user_prompt = StoryPrompts.HE_THONG['user_template'].format(
            chu_de=theme,
            boi_canh=setting
        )
        if custom_requirements:
            user_prompt += f"\n\nYÊU CẦU BỔ SUNG:\n{custom_requirements}"

        if max_tokens is None:
            max_tokens = self.max_completion_tokens

        start_time = time.time()
        system_prompt = StoryPrompts.HE_THONG['system'] + "\n\nOUTPUT FORMAT (bắt buộc):\n- Dòng đầu: TIÊU ĐỀ: <tiêu đề truyện>\n- Bỏ một dòng trống, rồi bắt đầu phần nội dung truyện thuần túy."

        try:
            send_discord_message("🤖 (Gemini) Generating he thong story in single-shot...")
            prompt = system_prompt + "\n\n" + user_prompt
            model = self._gemini.GenerativeModel(self.model)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens
                )
            )
            raw_text = response.text.strip()
            title, story_content = self._parse_title_and_content(raw_text, fallback=theme)
            generation_time = time.time() - start_time
            word_count = len(story_content.split())
            file_path = self._save_story(title, story_content, theme, setting)

            metadata = {'model': self.model, 'genre': 'he_thong', 'theme': theme, 'setting': setting, 'word_count': word_count, 'generation_time': generation_time, 'timestamp': time.time(), 'custom_requirements': custom_requirements}
            self.save_history({'title': title, 'file_path': file_path, 'metadata': metadata})

            send_discord_message(f"💾 Đã lưu truyện: {file_path}")
            send_discord_message(f"✅ Hoàn tất tạo truyện hệ thống! Độ dài: {word_count:,} từ | Thời gian: {generation_time:.1f}s")

            return {'title': title, 'content': story_content, 'theme': theme, 'setting': setting, 'word_count': word_count, 'generation_time': generation_time, 'file_path': file_path, 'metadata': metadata}
        except Exception as e:
            send_discord_message(f"❌ Lỗi khi tạo truyện hệ thống: {e}")
            raise

    def generate_game_world_story(
        self,
        theme: Optional[str] = None,
        setting: Optional[str] = None,
        custom_requirements: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.9
    ) -> Dict[str, any]:
        """Tạo truyện thể loại 'vào thế giới game'."""
        import random
        if theme is None:
            theme = random.choice(StoryPrompts.VAO_THE_GIOI_GAME['themes'])
        if setting is None:
            setting = random.choice(StoryPrompts.VAO_THE_GIOI_GAME['settings'])

        send_discord_message("📝 Bắt đầu tạo truyện vào thế giới game...")
        send_discord_message(f"   Chủ đề: {theme}")
        send_discord_message(f"   Bối cảnh: {setting}")

        user_prompt = StoryPrompts.VAO_THE_GIOI_GAME['user_template'].format(
            chu_de=theme,
            boi_canh=setting
        )
        if custom_requirements:
            user_prompt += f"\n\nYÊU CẦU BỔ SUNG:\n{custom_requirements}"

        if max_tokens is None:
            max_tokens = self.max_completion_tokens

        start_time = time.time()
        system_prompt = StoryPrompts.VAO_THE_GIOI_GAME['system'] + "\n\nOUTPUT FORMAT (bắt buộc):\n- Dòng đầu: TIÊU ĐỀ: <tiêu đề truyện>\n- Bỏ một dòng trống, rồi bắt đầu phần nội dung truyện thuần túy."

        try:
            send_discord_message("🤖 (Gemini) Generating game-world story in single-shot...")
            prompt = system_prompt + "\n\n" + user_prompt
            model = self._gemini.GenerativeModel(self.model)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens
                )
            )
            raw_text = response.text.strip()
            title, story_content = self._parse_title_and_content(raw_text, fallback=theme)
            generation_time = time.time() - start_time
            word_count = len(story_content.split())
            file_path = self._save_story(title, story_content, theme, setting)

            metadata = {'model': self.model, 'genre': 'vao_the_gioi_game', 'theme': theme, 'setting': setting, 'word_count': word_count, 'generation_time': generation_time, 'timestamp': time.time(), 'custom_requirements': custom_requirements}
            self.save_history({'title': title, 'file_path': file_path, 'metadata': metadata})

            send_discord_message(f"💾 Đã lưu truyện: {file_path}")
            send_discord_message(f"✅ Hoàn tất tạo truyện vào thế giới game! Độ dài: {word_count:,} từ | Thời gian: {generation_time:.1f}s")

            return {'title': title, 'content': story_content, 'theme': theme, 'setting': setting, 'word_count': word_count, 'generation_time': generation_time, 'file_path': file_path, 'metadata': metadata}
        except Exception as e:
            send_discord_message(f"❌ Lỗi khi tạo truyện vào thế giới game: {e}")
            raise
    
    def generate_random_mix_story(
        self,
        the_loai_chinh: Optional[str] = None,
        the_loai_phu: Optional[str] = None,
        nhan_vat: Optional[str] = None,
        boi_canh: Optional[str] = None,
        mo_tip: Optional[str] = None,
        custom_requirements: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.9  # Cao hơn cho sáng tạo
    ) -> Dict[str, any]:
        """
        Tạo truyện RANDOM MIX - kết hợp ngẫu nhiên nhiều thể loại
        
        Args:
            the_loai_chinh: Thể loại chính (nếu None → random)
            the_loai_phu: Thể loại phụ (nếu None → random)
            nhan_vat: Nhân vật chính (nếu None → random)
            boi_canh: Bối cảnh (nếu None → random)
            mo_tip: Mô típ cốt truyện (nếu None → random)
            custom_requirements: Yêu cầu tùy chỉnh
            max_tokens: Số token tối đa
            temperature: Độ sáng tạo (0.9 - cao)
        
        Returns:
            Dict chứa thông tin truyện
        """
        import random
        
        # Kiểm tra xem user có EXPLICITLY yêu cầu AI chọn hay không
        # Chỉ gọi AI khi user ghi rõ trong custom_requirements
        custom_lower = (custom_requirements or '').lower()
        user_wants_ai_selection = any([
            'ai chọn' in custom_lower,
            'ai select' in custom_lower,
            'thông minh' in custom_lower,
            'hợp lý' in custom_lower and 'chọn' in custom_lower,
            'intelligent' in custom_lower
        ])

        if user_wants_ai_selection:
            send_discord_message("🤖 Đang để AI chọn kết hợp hợp lý...")
            try:
                selected = self._ai_select_coherent_combination()
                # Chỉ override params nào đang empty
                if not the_loai_chinh or not the_loai_chinh.strip():
                    the_loai_chinh = selected['the_loai_chinh']
                if not the_loai_phu or not the_loai_phu.strip():
                    the_loai_phu = selected['the_loai_phu']
                if not nhan_vat or not nhan_vat.strip():
                    nhan_vat = selected['nhan_vat']
                if not boi_canh or not boi_canh.strip():
                    boi_canh = selected['boi_canh']
                if not mo_tip or not mo_tip.strip():
                    mo_tip = selected['mo_tip']
                send_discord_message(f"✅ AI đã chọn: {the_loai_chinh[:30]}... / {nhan_vat[:30]}... / {boi_canh[:30]}...")
            except Exception as e:
                send_discord_message(f"⚠️ AI selection thất bại, dùng random: {e}")
                user_wants_ai_selection = False
        
        # Random selection cho các param bị thiếu (nếu không dùng AI)
        if not user_wants_ai_selection:
            if not the_loai_chinh or not the_loai_chinh.strip():
                the_loai_chinh = random.choice(StoryPrompts.RANDOM_MIX['the_loai_chinh'])
            if not the_loai_phu or not the_loai_phu.strip():
                the_loai_phu = random.choice(StoryPrompts.RANDOM_MIX['the_loai_phu'])
            if not nhan_vat or not nhan_vat.strip():
                nhan_vat = random.choice(StoryPrompts.RANDOM_MIX['nhan_vat'])
            
            if not boi_canh or not boi_canh.strip():
                boi_canh = random.choice(StoryPrompts.RANDOM_MIX['boi_canh'])
            
            if not mo_tip or not mo_tip.strip():
                mo_tip = random.choice(StoryPrompts.RANDOM_MIX['mo_tip'])
        
        send_discord_message("🎲 Bắt đầu tạo truyện RANDOM MIX...")
        send_discord_message(f"   🎭 Thể loại chính: {the_loai_chinh}")
        send_discord_message(f"   🎨 Thể loại phụ: {the_loai_phu}")
        send_discord_message(f"   👤 Nhân vật: {nhan_vat[:50]}...")
        send_discord_message(f"   🏙️  Bối cảnh: {boi_canh[:50]}...")
        send_discord_message(f"   📖 Mô típ: {mo_tip[:50]}...")
        
        # Tạo prompt
        user_prompt = StoryPrompts.RANDOM_MIX['user_template'].format(
            the_loai_chinh=the_loai_chinh,
            the_loai_phu=the_loai_phu,
            nhan_vat=nhan_vat,
            boi_canh=boi_canh,
            mo_tip=mo_tip
        )
        
        if custom_requirements:
            user_prompt += f"\n\nYÊU CẦU BỔ SUNG:\n{custom_requirements}"
        
        # Auto max_tokens
        if max_tokens is None:
            max_tokens = self.max_completion_tokens
        
        send_discord_message(f"⚙️  max_tokens: {max_tokens}, temperature: {temperature}")
        
        # Single-shot generation: build system + user prompt and call model once.
        start_time = time.time()

        system_prompt = (
            "Bạn là nhà văn đa năng chuyên kết hợp nhiều thể loại.\n\n"
            "PHONG CÁCH BẮT BUỘC:\n"
            "- Kể theo NGÔI THỨ NHẤT (\"tôi\")\n"
            "- Hài hước + rùng rợn nhẹ + hiện đại\n"
            "- Giọng văn tự nhiên, gần gũi\n"
            "- Nhiều hội thoại sinh động\n"
            "- Châm biếm xã hội nhẹ nhàng\n"
            "- Cân bằng các thể loại mượt mà\n"
            "- KHÔNG DÙNG tiêu đề ##\n\n"
            "TWIST:\n"
            "- Phải bất ngờ nhưng hợp lý\n"
            "- Gây ấn tượng mạnh\n"
            "- Không sáo rỗng\n\n"
            "KẾT HỢP THỂ LOẠI:\n"
            "- Hài + Kinh dị: Cười rồi giật mình\n"
            "- Vả mặt + Siêu nhiên: Lộ thân phận + ma quỷ\n"
            "- Công nghệ + Tâm linh: AI gặp ma\n"
            "- Tự nhiên, không gượng ép"
            "\nYÊU CẦU VỀ GIỌNG VĂN VÀ TỪ VỰNG:\n"
            "- Viết bằng tiếng Việt đời thường, giản dị và thân mật; ngôn ngữ gần gũi.\n"
            "- Tránh dùng từ mượn tiếng Anh hoặc tiếng lóng Anh; thay bằng từ thuần Việt tương đương.\n"
        )

        # YÊU CẦU VỀ ĐỊNH DẠNG OUTPUT: trả về tiêu đề cùng lúc với nội dung
        system_prompt += (
            "\n\nOUTPUT FORMAT (bắt buộc):\n"
            "- Dòng đầu: TIÊU ĐỀ: <tiêu đề truyện>\n"
            "- Bỏ một dòng trống, rồi bắt đầu phần nội dung truyện thuần túy.\n"
            "- KHÔNG in thêm tiêu đề hay phân đoạn khác.\n"
        )
        try:
            send_discord_message("🤖 (Gemini) Generating random-mix story in single-shot...")
            prompt = system_prompt + "\n\n" + user_prompt

            # Sử dụng GenerativeModel API của Gemini
            model = self._gemini.GenerativeModel(self.model)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens
                )
            )
            
            raw_text = response.text.strip()
            title, story_content = self._parse_title_and_content(raw_text, fallback=f"{the_loai_chinh} + {mo_tip}")
            generation_time = time.time() - start_time
            word_count = len(story_content.split())

            file_path = self._save_story_random_mix(title, story_content, the_loai_chinh, the_loai_phu, nhan_vat, boi_canh, mo_tip)

            metadata = {
                'model': self.model,
                'genre': 'random_mix',
                'the_loai_chinh': the_loai_chinh,
                'the_loai_phu': the_loai_phu,
                'nhan_vat': nhan_vat,
                'boi_canh': boi_canh,
                'mo_tip': mo_tip,
                'word_count': word_count,
                'generation_time': generation_time,
                'timestamp': time.time(),
                'custom_requirements': custom_requirements,
                'tokens_used': None,
                'chapters': []
            }

            history_entry = {
                'title': title,
                'file_path': file_path,
                'metadata': metadata
            }
            self.save_history(history_entry)

            result = {
                'title': title,
                'content': story_content,
                'the_loai_chinh': the_loai_chinh,
                'the_loai_phu': the_loai_phu,
                'nhan_vat': nhan_vat,
                'boi_canh': boi_canh,
                'mo_tip': mo_tip,
                'word_count': word_count,
                'generation_time': generation_time,
                'file_path': file_path,
                'metadata': metadata
            }

            send_discord_message(f"💾 Đã lưu: {file_path}")
            send_discord_message(f"✅ Hoàn tất tạo truyện Random Mix! Độ dài: {word_count:,} từ | Thời gian: {generation_time:.1f}s")

            return result

        except Exception as e:
            send_discord_message(f"❌ Lỗi: {e}")
            raise

    def generate_random_mix_preview(
        self,
        the_loai_chinh: Optional[str] = None,
        the_loai_phu: Optional[str] = None,
        nhan_vat: Optional[str] = None,
        boi_canh: Optional[str] = None,
        mo_tip: Optional[str] = None,
        custom_requirements: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.9
    ) -> Dict[str, any]:
        """
        Generate a full random-mix story (title + content) and produce a short summary in one call.
        Returns dict: {title, content, summary, file_path, metadata}
        """
        # Reuse existing story generation
        result = self.generate_random_mix_story(
            the_loai_chinh=the_loai_chinh,
            the_loai_phu=the_loai_phu,
            nhan_vat=nhan_vat,
            boi_canh=boi_canh,
            mo_tip=mo_tip,
            custom_requirements=custom_requirements,
            max_tokens=max_tokens,
            temperature=temperature
        )

        title = result.get('title')
        content = result.get('content')

        # Create a short summary (văn án) using OpenAI if available, otherwise fallback to first 200-300 chars
        summary = None
        try:
            if self._openai:
                prompt = (
                    "Tóm tắt ngắn (2-4 câu) cho truyện sau bằng tiếng Việt, dùng giọng hấp dẫn, không spoil hết cốt truyện:\n\n"
                    f"{content[:4000]}"
                )
                resp = self._openai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Bạn là chuyên gia viết văn án ngắn hấp dẫn cho truyện dài."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=400
                )
                raw = resp.choices[0].message.content.strip()
                summary = raw
        except Exception:
            summary = None

        if not summary:
            # fallback: take first 400-600 characters and make a concise paragraph
            snippet = content.strip()[:600]
            if len(snippet) < 200:
                summary = snippet
            else:
                # try to cut at sentence end
                idx = snippet.rfind('.')
                if idx > 80:
                    summary = snippet[:idx+1]
                else:
                    summary = snippet + '...'

        # Attach the summary to result and return
        result['summary'] = summary
        return result
    
    def _extract_title(self, content: str, fallback: str) -> str:
        """Trích xuất tiêu đề từ nội dung hoặc dùng fallback"""
        lines = content.split('\n')
        for line in lines[:10]:  # Kiểm tra 10 dòng đầu
            line = line.strip()
            if line and len(line) < 100:  # Tiêu đề không quá dài
                # Loại bỏ các ký tự đặc biệt đầu dòng
                title = line.lstrip('#*-_ ')
                if title:
                    return title
        
        # Nếu không tìm thấy, tạo tiêu đề từ theme
        return f"Truyện Kinh Dị: {fallback[:50]}"
    
    def _ai_select_coherent_combination(self, user_idea: str = "") -> Dict[str, str]:
        """
        Sử dụng AI để chọn kết hợp hợp lý giữa các yếu tố random_mix
        dựa trên ý tưởng của user hoặc hot trends hiện tại
        
        Args:
            user_idea: Ý tưởng của user (VD: "tình cảm bị phản bội rồi trả thù chồng cũ")
        
        Returns:
            Dict với keys: the_loai_chinh, the_loai_phu, nhan_vat, boi_canh, mo_tip
        """
        import random
        
        # Random samples từ mỗi danh sách để tham khảo
        sample_main = random.sample(StoryPrompts.RANDOM_MIX['the_loai_chinh'], min(15, len(StoryPrompts.RANDOM_MIX['the_loai_chinh'])))
        sample_sub = random.sample(StoryPrompts.RANDOM_MIX['the_loai_phu'], min(15, len(StoryPrompts.RANDOM_MIX['the_loai_phu'])))
        sample_char = random.sample(StoryPrompts.RANDOM_MIX['nhan_vat'], min(10, len(StoryPrompts.RANDOM_MIX['nhan_vat'])))
        sample_setting = random.sample(StoryPrompts.RANDOM_MIX['boi_canh'], min(10, len(StoryPrompts.RANDOM_MIX['boi_canh'])))
        sample_motif = random.sample(StoryPrompts.RANDOM_MIX['mo_tip'], min(15, len(StoryPrompts.RANDOM_MIX['mo_tip'])))
        
        # Thêm phần user idea nếu có
        user_section = ""
        if user_idea:
            user_section = f"""
Ý TƯỞNG CỦA USER (ƯU TIÊN CAO NHẤT):
"{user_idea}"

→ Hãy dựa vào ý tưởng này để tạo kết hợp phù hợp. Có thể lấy cảm hứng từ danh sách gợi ý hoặc sáng tạo hoàn toàn mới.
"""
        
        selection_prompt = f"""Bạn là chuyên gia tạo nội dung hot trend, đời thường, hiện đại. Nhiệm vụ của bạn là tạo kết hợp hấp dẫn, dễ hiểu, gần gũi với cuộc sống.

{user_section}

DANH SÁCH GỢI Ý (tham khảo hoặc sáng tạo mới):

THỂ LOẠI CHÍNH (tham khảo):
{chr(10).join(f"{i+1}. {x}" for i, x in enumerate(sample_main))}

THỂ LOẠI PHỤ (tham khảo):
{chr(10).join(f"{i+1}. {x}" for i, x in enumerate(sample_sub))}

NHÂN VẬT CHÍNH (tham khảo):
{chr(10).join(f"{i+1}. {x[:80]}..." for i, x in enumerate(sample_char))}

BỐI CẢNH (tham khảo):
{chr(10).join(f"{i+1}. {x[:60]}..." for i, x in enumerate(sample_setting))}

MÔ TÍP CỐT TRUYỆN (tham khảo):
{chr(10).join(f"{i+1}. {x[:70]}..." for i, x in enumerate(sample_motif))}

NGUYÊN TẮC SÁNG TẠO:
✅ ƯU TIÊN: Đời thường, hiện đại, hot trend (TikTok, Instagram, drama đời thực)
✅ DỄ HIỂU: Không quá xoắn não, không triết lý sâu xa
✅ GẦN GŨI: Tình huống có thể xảy ra hoặc người ta mong muốn xem
✅ HẤP DẪN: Drama rõ ràng, conflict mạnh, cảm xúc cao
❌ TRÁNH: Quá văn học, quá điện ảnh, quá siêu nhiên phức tạp

VÍ DỤ HOT TREND:
- "Tình cảm bị phản bội → Trả thù chồng cũ bằng cách thành công vượt mặt"
- "Nữ phụ bị ghét nhưng thực ra là người tốt nhất"
- "Lạc trên tàu/khách sạn với quy tắc kỳ lạ để sống sót"
- "Trọng sinh về quá khứ sửa sai lầm, tránh người toxic"
- "Giả nghèo test lòng người, vạch mặt kẻ vật chất"

TRẢ VỀ JSON:
{{
  "the_loai_chinh": "thể loại chính (ưu tiên đời thường, hiện đại)",
  "the_loai_phu": "thể loại phụ (drama, tình cảm, báo thù...)",
  "nhan_vat": "nhân vật cụ thể (VD: '💔 Cô gái 28 tuổi vừa ly hôn', '🎭 Nữ phụ bị ghét vô lý')",
  "boi_canh": "bối cảnh rõ ràng (VD: 'Công ty đa quốc gia Sài Gòn', 'Khách sạn 5 sao có quy tắc bí ẩn')",
  "mo_tip": "mô típ hot trend (VD: 'Trả thù người cũ bằng thành công', 'Sống sót theo luật lệ kỳ lạ')",
  "ly_do": "giải thích ngắn gọn tại sao kết hợp này hot, hấp dẫn, dễ xem (2-3 câu)"
}}

CHỈ TRẢ VỀ JSON."""

        try:
            # Dùng OpenAI cho AI selection (tránh Gemini safety filters)
            if not self._openai:
                raise Exception("OpenAI client not available")
            
            response = self._openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Bạn là chuyên gia tạo nội dung hot trend, đời thường, hiện đại. Ưu tiên drama rõ ràng, dễ hiểu, gần gũi. Tránh quá văn học hoặc triết lý sâu xa. Nếu user có ý tưởng cụ thể, hãy dựa vào đó để tạo kết hợp phù hợp."},
                    {"role": "user", "content": selection_prompt}
                ],
                temperature=0.9,
                max_tokens=2000,
                response_format={"type": "json_object"}
            )
            
            raw = response.choices[0].message.content.strip()
            result = json.loads(raw)
            
            send_discord_message(f"💡 AI đã chọn kết hợp: {result.get('ly_do', 'N/A')[:200]}")
            
            return {
                'the_loai_chinh': result.get('the_loai_chinh', sample_main[0]),
                'the_loai_phu': result.get('the_loai_phu', sample_sub[0]),
                'nhan_vat': result.get('nhan_vat', sample_char[0]),
                'boi_canh': result.get('boi_canh', sample_setting[0]),
                'mo_tip': result.get('mo_tip', sample_motif[0]),
                'ly_do': result.get('ly_do', 'AI đã chọn kết hợp hợp lý')
            }
            
        except Exception as e:
            error_msg = str(e)
            send_discord_message(f"⚠️ OpenAI selection failed: {error_msg[:100]}, dùng random")
            
            # Fallback: random selection
            return {
                'the_loai_chinh': random.choice(sample_main),
                'the_loai_phu': random.choice(sample_sub),
                'nhan_vat': random.choice(sample_char),
                'boi_canh': random.choice(sample_setting),
                'mo_tip': random.choice(sample_motif),
                'ly_do': 'Random selection (AI unavailable)'
            }

    
    def _extract_title_face_slap(self, content: str, fallback: str) -> str:
        """Trích xuất tiêu đề cho truyện vả mặt"""
        lines = content.split('\n')
        for line in lines[:10]:
            line = line.strip()
            if line and len(line) < 100:
                title = line.lstrip('#*-_ ')
                if title:
                    return title
        
        # Tạo tiêu đề từ theme
        return f"{fallback[:70]}"
    
    def _extract_title_random_mix(self, content: str, the_loai: str, mo_tip: str) -> str:
        """Trích xuất tiêu đề cho truyện random mix"""
        lines = content.split('\n')
        for line in lines[:10]:
            line = line.strip()
            if line and len(line) < 100:
                title = line.lstrip('#*-_ ')
                if title:
                    return title
        
        # Tạo title từ thể loại + mô típ
        return f"{the_loai} + {mo_tip[:40]}"

    def _parse_title_and_content(self, raw_text: str, fallback: str = "Truyện") -> tuple[str, str]:
        """Parse model response to extract explicit title + content.

        Supports JSON like {"title":"...","content":"..."} or
        a plain-text format where the first non-empty line starts with
        'TIÊU ĐỀ:' (case-insensitive). Falls back to extracting title
        heuristically from content when no explicit title is found.
        Returns (title, content).
        """
        import json

        text = raw_text.strip()

        # Try JSON first
        if text.startswith('{'):
            try:
                obj = json.loads(text)
                title = obj.get('title') or obj.get('tiêu_đề') or obj.get('tieu_de')
                content = obj.get('content') or obj.get('body') or obj.get('nội_dung') or obj.get('noi_dung')
                if title and content:
                    return title.strip(), content.strip()
            except Exception:
                pass

        # Plain text: look for TIÊU ĐỀ: prefix on first non-empty line
        lines = text.split('\n')
        first_idx = None
        for i, l in enumerate(lines):
            if l.strip():
                first_idx = i
                break

        if first_idx is not None:
            first_line = lines[first_idx].strip()
            lower = first_line.lower()
            if lower.startswith('tiêu đề:') or lower.startswith('tieu de:') or lower.startswith('title:'):
                # Extract title after the colon
                parts = first_line.split(':', 1)
                title = parts[1].strip() if len(parts) > 1 else fallback

                # Build content from remaining lines after the title line
                remaining = '\n'.join(lines[first_idx+1:]).lstrip('\n').strip()
                # If there's a leading blank line, strip it
                if remaining.startswith('\n'):
                    remaining = remaining.lstrip('\n')
                # If remaining is empty, fallback to entire raw text
                content = remaining if remaining else text
                return title, content

        # No explicit title found: fallback
        title = self._extract_title(text, fallback)
        return title, text
    
    def _save_story(self, title: str, content: str, theme: str, setting: str) -> str:
        """Lưu truyện vào file"""
        # Tạo tên file an toàn
        import re
        safe_title = re.sub(r'[^\w\s-]', '', title)
        safe_title = re.sub(r'[-\s]+', '_', safe_title)
        safe_title = safe_title[:100]  # Giới hạn độ dài
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{safe_title}.txt"
        file_path = os.path.join(STORIES_DIR, filename)
        
        # Tạo nội dung file với metadata
        full_content = f"""{'='*80}
TIÊU ĐỀ: {title}
{'='*80}

Chủ đề: {theme}
Bối cảnh: {setting}
Thời gian tạo: {time.strftime("%Y-%m-%d %H:%M:%S")}

{'='*80}

{content}

{'='*80}
Kết thúc truyện
{'='*80}
"""
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(full_content)
            # Also write a companion file that contains only the raw story content
            try:
                content_only_path = os.path.splitext(file_path)[0] + "_content.txt"
                with open(content_only_path, 'w', encoding='utf-8') as cf:
                    cf.write(content)
            except Exception:
                pass
            return file_path
        except Exception as e:
            send_discord_message(f"⚠️ Lỗi khi lưu file: {e}")
            # Thử lưu với tên đơn giản hơn
            file_path = os.path.join(STORIES_DIR, f"{timestamp}_story.txt")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(full_content)
            return file_path
    
    def _save_story_face_slap(self, title: str, content: str, theme: str, vai_tro_gia: str, setting: str) -> str:
        """Lưu truyện vả mặt vào file"""
        import re
        safe_title = re.sub(r'[^\w\s-]', '', title)
        safe_title = re.sub(r'[-\s]+', '_', safe_title)
        safe_title = safe_title[:100]
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_vamat_{safe_title}.txt"
        file_path = os.path.join(STORIES_DIR, filename)
        
        # Tạo nội dung file với metadata
        full_content = f"""{'='*80}
TIÊU ĐỀ: {title}
{'='*80}

Thể loại: Vả Mặt - Face Slap
Chủ đề: {theme}
Vai trò giả: {vai_tro_gia}
Bối cảnh: {setting}
Thời gian tạo: {time.strftime("%Y-%m-%d %H:%M:%S")}

{'='*80}

{content}

{'='*80}
Kết thúc truyện
{'='*80}
"""
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(full_content)
            # Also write a companion file that contains only the raw story content
            try:
                content_only_path = os.path.splitext(file_path)[0] + "_content.txt"
                with open(content_only_path, 'w', encoding='utf-8') as cf:
                    cf.write(content)
            except Exception:
                pass
            return file_path
        except Exception as e:
            send_discord_message(f"⚠️ Lỗi khi lưu file: {e}")
            file_path = os.path.join(STORIES_DIR, f"{timestamp}_vamat_story.txt")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(full_content)
            return file_path
    
    def _save_story_random_mix(
        self, title: str, content: str,
        the_loai_chinh: str, the_loai_phu: str,
        nhan_vat: str, boi_canh: str, mo_tip: str
    ) -> str:
        """Lưu truyện random mix vào file"""
        import re
        safe_title = re.sub(r'[^\w\s-]', '', title)
        safe_title = re.sub(r'[-\s]+', '_', safe_title)
        safe_title = safe_title[:100]
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_random_{safe_title}.txt"
        file_path = os.path.join(STORIES_DIR, filename)
        
        # Nội dung file
        full_content = f"""{'='*80}
TIÊU ĐỀ: {title}
{'='*80}

Thể loại: RANDOM MIX (Hài - Kinh dị - Vả mặt - Siêu nhiên - Hiện đại)
Thể loại chính: {the_loai_chinh}
Thể loại phụ: {the_loai_phu}
Nhân vật: {nhan_vat[:100]}...
Bối cảnh: {boi_canh[:100]}...
Mô típ: {mo_tip[:100]}...
Thời gian tạo: {time.strftime("%Y-%m-%d %H:%M:%S")}

{'='*80}

{content}

{'='*80}
Kết thúc truyện
{'='*80}
"""
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(full_content)
            # Also write a companion file that contains only the raw story content
            try:
                content_only_path = os.path.splitext(file_path)[0] + "_content.txt"
                with open(content_only_path, 'w', encoding='utf-8') as cf:
                    cf.write(content)
            except Exception:
                pass
            return file_path
        except Exception as e:
            send_discord_message(f"⚠️ Lỗi lưu file: {e}")
            file_path = os.path.join(STORIES_DIR, f"{timestamp}_random_story.txt")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(full_content)
            return file_path
    
    def generate_multiple_stories(
        self,
        count: int = 3,
        delay_between: int = 5,
        **kwargs
    ) -> List[Dict]:
        """
        Tạo nhiều truyện liên tiếp
        
        Args:
            count: Số lượng truyện cần tạo
            delay_between: Số giây chờ giữa các lần tạo (để tránh rate limit)
            **kwargs: Các tham số khác cho generate_horror_story()
        
        Returns:
            List các dict kết quả
        """
        results = []
        
        send_discord_message(f"📚 Bắt đầu tạo {count} truyện...")
        
        for i in range(count):
            send_discord_message(f"\n{'='*60}")
            send_discord_message(f"Tạo truyện {i+1}/{count}")
            send_discord_message(f"{'='*60}\n")
            
            try:
                result = self.generate_horror_story(**kwargs)
                results.append(result)
                
                # Chờ trước khi tạo truyện tiếp theo (trừ lần cuối)
                if i < count - 1:
                    send_discord_message(f"⏳ Chờ {delay_between}s trước khi tạo truyện tiếp...")
                    time.sleep(delay_between)
                    
            except Exception as e:
                send_discord_message(f"❌ Lỗi khi tạo truyện {i+1}: {e}")
                results.append({'error': str(e)})
        
        send_discord_message(f"\n✅ Hoàn tất! Đã tạo {len([r for r in results if 'error' not in r])}/{count} truyện thành công")
        
        return results
    
    def get_story_statistics(self) -> Dict:
        """Lấy thống kê các truyện đã tạo"""
        if not self.history:
            return {
                'total_stories': 0,
                'total_words': 0,
                'average_words': 0,
                'total_time': 0,
                'average_time': 0
            }
        
        total_words = sum(h['metadata'].get('word_count', 0) for h in self.history)
        total_time = sum(h['metadata'].get('generation_time', 0) for h in self.history)
        
        return {
            'total_stories': len(self.history),
            'total_words': total_words,
            'average_words': total_words // len(self.history) if self.history else 0,
            'total_time': total_time,
            'average_time': total_time / len(self.history) if self.history else 0,
            'models_used': list(set(h['metadata'].get('model', 'unknown') for h in self.history))
        }


# Hàm tiện ích để sử dụng trực tiếp
def create_horror_story(
    theme: Optional[str] = None,
    setting: Optional[str] = None,
    model: str = "gpt-4-turbo",
    **kwargs
) -> Dict:
    """
    Hàm tiện ích để tạo truyện kinh dị nhanh chóng
    
    Args:
        theme: Chủ đề truyện
        setting: Bối cảnh
        model: Model OpenAI (mặc định "gpt-4-turbo" - khuyến nghị cho truyện dài)
               - "gpt-4-turbo" hoặc "gpt-4o": Tốt nhất, 128k context
               - "gpt-3.5-turbo-16k": Rẻ hơn, vẫn đủ tốt
               - "gpt-4": Context nhỏ (8k), chỉ phù hợp truyện ngắn
    
    Usage:
        result = create_horror_story()
        print(result['content'])
    """
    generator = StoryGenerator(model=model)
    return generator.generate_horror_story(theme=theme, setting=setting, **kwargs)


if __name__ == "__main__":
    # Test tạo 1 truyện
    print("="*80)
    print("TEST TẠO TRUYỆN KINH DỊ (CHIA THÀNH 10 CHƯƠNG)")
    print("="*80)
    
    generator = StoryGenerator(model="gpt-4-turbo")  # Hoặc "gpt-3.5-turbo-16k", "gpt-4o"
    
    # Tạo 1 truyện với chủ đề ngẫu nhiên
    result = generator.generate_horror_story()
    
    print("\n" + "="*80)
    print(f"TIÊU ĐỀ: {result['title']}")
    print("="*80)
    print(f"\nChủ đề: {result['theme']}")
    print(f"Bối cảnh: {result['setting']}")
    print(f"Số từ: {result['word_count']:,}")
    print(f"Thời gian: {result['generation_time']:.1f}s")
    print(f"File: {result['file_path']}")
    
    # Hiển thị chi tiết các chương
    if 'chapters' in result['metadata']:
        print("\n📚 CÁC CHƯƠNG (10 chương):")
        for i, ch in enumerate(result['metadata']['chapters'], 1):
            print(f"  {i:2d}. {ch['name']}: {ch['word_count']:,} từ")
    
    print("\n" + "="*80)
    print("NỘI DUNG (1000 ký tự đầu):")
    print("="*80)
    print(result['content'][:1000] + "...")
    print("\n" + "="*80)
    
    # Hiển thị thống kê
    stats = generator.get_story_statistics()
    print("\nTHỐNG KÊ:")
    print(f"  Tổng số truyện: {stats['total_stories']}")
    print(f"  Tổng số từ: {stats['total_words']:,}")
    print(f"  Trung bình: {stats['average_words']:,} từ/truyện")
    print("="*80)

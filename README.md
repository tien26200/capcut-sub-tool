# CapCut Subtitle Assistant

Ứng dụng Windows tạo phụ đề và thêm một text track vào dự án CapCut.

## Cách dùng

1. Lưu dự án trong CapCut.
2. Mở ứng dụng, bấm **Quét dự án** để tìm draft CapCut trên máy, hoặc chọn thư mục dự án.
3. Chọn clip trong dự án. Ứng dụng đọc đường dẫn nguồn và tọa độ clip trên timeline từ `draft_content.json`.
4. Chọn cách chia: theo câu, số từ, độ dài dòng hoặc từng từ.
5. Chọn ngôn ngữ tiếng Việt, tiếng Anh hoặc tự nhận diện; chỉnh màu nếu cần.
6. Có thể xem trước phụ đề, sau đó bấm **Tạo phụ đề vào dự án**.

Ứng dụng tạo bản `.backup` của draft trước khi ghi. Đóng dự án trong CapCut trước khi chèn để tránh CapCut ghi đè thay đổi. Không cần tự nhập link hoặc chọn file video thủ công.

## Căn thời gian và kịch bản

Nhận diện tiếng Việt bằng `faster-whisper` và sử dụng timestamp từng từ. Thời gian phụ đề được đổi từ source time sang vị trí clip trên timeline, kể cả khi clip bị trim. Nếu có nhiều clip, chọn clip cần tạo phụ đề trong danh sách.

Ô kịch bản tùy chọn: điền bản lời thoại đã chuẩn hóa. Để tránh lệch timing, bản này chỉ thay chữ khi số từ khớp với số từ nhận diện; nếu không khớp, ứng dụng giữ chữ nhận diện và báo trạng thái.

## Giới hạn hiện tại

- CapCut không cung cấp cho ứng dụng này API điều khiển phiên đang mở. Vì vậy dự án được lấy từ draft đã lưu trên máy; cần lưu dự án trước khi quét và đóng CapCut trước lúc ghi.
- Chọn một clip mỗi lần. Nếu dự án có nhiều đoạn ghép nối, hãy xử lý từng clip hoặc dùng một clip nguồn đã ghép sẵn.
- Model Whisper tải về khi chạy lần đầu, nên lần đó cần Internet.
- Kiểm thử với bản sao dự án trước khi dùng trên công việc quan trọng.

## Phát triển

```bash
pip install -r requirements.txt
python -m unittest -v
python capcut_sub_tool.py
```

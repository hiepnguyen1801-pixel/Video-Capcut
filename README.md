# Video-Capcut

Script `capcut_edit.py` dùng **FFmpeg** để lấy video gốc làm nền rồi áp dụng **đủ các bước edit, đúng thứ tự**:

| # | Bước | Cách làm trong FFmpeg |
|---|------|-----------------------|
| 1 | Ngà lạnh `brightness(1.1) saturate(0.8) contrast(1.05) hue-rotate(5deg)` | dịch từng hàm CSS sang `lutrgb` / `colorchannelmixer` |
| 2 | Sắc nét 4K `contrast(1.2) saturate(1.15) brightness(1.05)` | như trên |
| 3 | Sáng ấm `sepia(0.3) saturate(1.2) brightness(1.05) contrast(1.05)` | như trên |
| – | ~~Phim điện ảnh~~, ~~Trắng đen~~ | **đã bỏ** |
| 6 | Pulse Zoom (thu phóng lặp lại) | `perspective`, zoom 1 → 1.08 → 1 theo hàm sin, chu kỳ 2s |
| 7 | Gentle Shake | `scale` ×1.04 rồi `crop` về kích thước gốc, dịch x, y theo tổng các hàm sin/cos |
| 8 | Hard Shake / Bounce | `scale` ×1.10 rồi `crop` rung nhẹ mỗi 0.5s, tắt dần theo `exp`, trục dọc nảy kiểu bounce |
| 9 | Tốc độ 1.15x | `setpts=PTS/1.15` + `atempo=1.15` |
| 10 | Lật ngang | `hflip` |
| 11 | Giữ 2s, bỏ 1s, lặp đến hết | `select` / `aselect` với `mod(t,3) < 2` |
| 12 | ~~Light Leaks / Film Burn~~ | **đang tắt**; đặt `LIGHT_LEAKS = True` để bật lại |
| 13 | Xuất khung 9:16 (1080×1920) | mặc định: video ở giữa, nền là chính video làm mờ; `--fit crop` để cắt giữa cho kín khung |
| 17 | ~~Bóng ma thị giác~~ | **đang tắt**; đặt `GHOST = True` để bật lại |
| 18 | Nhiễu hạt 10% | `noise=c0s=10:c0f=t+u` trên kênh sáng, hạt thay đổi theo từng khung |
| 19 | Lớp phủ 3% | video trong `video_lop_phu/` đưa về khung 9:16, tự lặp nếu ngắn hơn, trộn lên trên bằng `mix` với độ mờ 3% |

Các bộ lọc màu được tính theo đúng ma trận trong đặc tả CSS Filter Effects, áp từng hàm một và clamp sau mỗi hàm giống trình duyệt.

## Cách dùng

Yêu cầu: `ffmpeg`, `ffprobe`, Python 3.

### Edit theo thư mục (khuyên dùng)

| Thư mục | Để làm gì |
|---|---|
| `video_can_edit/` | chép các video cần edit vào đây |
| `video_lop_phu/` | chép video lớp phủ vào đây (không bắt buộc; ảnh .png/.jpg cũng được) |
| `output/` | video kết quả, đặt tên `01_<tên gốc>.mp4`, `02_...` theo thứ tự |

Chạy (Windows: bấm đúp `chay.bat`):

```bash
python capcut_edit.py
```

- Video được edit **lần lượt theo thứ tự chép vào** thư mục `video_can_edit` (theo ngày tạo file, không theo tên).
- Lớp phủ ghép theo thứ tự: video 1 ↔ lớp phủ 1, video 2 ↔ lớp phủ 2, … Chỉ có 1 lớp phủ thì dùng chung cho mọi video; hết lớp phủ thì quay vòng lại.
- Lớp phủ ngắn hơn video thì tự lặp lại; độ mờ đặt ở `OVERLAY_OPACITY = 0.03` (3%).
- Video đã có trong `output` sẽ được bỏ qua khi chạy lại; thêm `--force` để làm lại hết.

### Edit 1 file

```bash
python capcut_edit.py input.mp4 output.mp4 --overlay lop_phu.mp4
```

Tuỳ chọn:

- `--force` — làm lại cả video đã có trong `output`
- `--fit blur` / `--fit crop` — cách đưa vào khung 9:16 (mặc định `blur`)
- `--crf 18` — chất lượng x264 (thấp hơn = đẹp hơn, file nặng hơn)
- `--preset medium` — tốc độ encode x264 (`veryfast` nhanh hơn)
- `--dry-run` — chỉ in lệnh ffmpeg đầy đủ để xem hoặc chạy tay

Các thông số (biên độ zoom, độ rung, độ đậm vệt sáng, ...) nằm ở đầu file `capcut_edit.py`.

Các bộ lọc màu 1, 2, 3 được áp chồng lên nhau theo thứ tự.
Độ dài video ra ≈ độ dài gốc ÷ 1.15 × 2/3.

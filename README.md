# Video-Capcut

Script `capcut_edit.py` dùng **FFmpeg** để lấy video gốc làm nền rồi áp dụng **đủ 12 bước edit, đúng thứ tự**:

| # | Bước | Cách làm trong FFmpeg |
|---|------|-----------------------|
| 1 | Ngà lạnh `brightness(1.1) saturate(0.8) contrast(1.05) hue-rotate(5deg)` | dịch từng hàm CSS sang `lutrgb` / `colorchannelmixer` |
| 2 | Sắc nét 4K `contrast(1.2) saturate(1.15) brightness(1.05)` | như trên |
| 3 | Phim điện ảnh `contrast(1.15) saturate(0.9) brightness(0.9) sepia(0.2)` | như trên |
| 4 | Trắng đen `grayscale(1) contrast(1.3) brightness(0.9)` | như trên |
| 5 | Sáng ấm `sepia(0.3) saturate(1.2) brightness(1.05) contrast(1.05)` | như trên |
| 6 | Pulse Zoom (thu phóng lặp lại) | `perspective` với hệ số zoom `1 + A·(1−cos(2πt/T))/2` |
| 7 | Gentle Shake | `scale` ×1.04 rồi `crop` dịch x, y theo tổng các hàm sin/cos |
| 8 | Hard Shake / Bounce | `scale` ×1.10 rồi `crop` rung mạnh theo nhịp 0.5s, tắt dần theo `exp` |
| 9 | Tốc độ 1.25x | `setpts=PTS/1.25` + `atempo=1.25` |
| 10 | Lật ngang | `hflip` |
| 11 | Giữ 2s, bỏ 1s, lặp đến hết | `select` / `aselect` với `mod(t,3) < 2` |
| 12 | Light Leaks / Film Burn | vệt sáng sinh bằng `geq`, hòa trộn `blend=screen` |

Các bộ lọc màu được tính theo đúng ma trận trong đặc tả CSS Filter Effects, áp từng hàm một và clamp sau mỗi hàm giống trình duyệt.

## Cách dùng

Yêu cầu: `ffmpeg`, `ffprobe`, Python 3.

```bash
python3 capcut_edit.py input.mp4 output.mp4
```

Tuỳ chọn:

- `--crf 18` — chất lượng x264 (thấp hơn = đẹp hơn, file nặng hơn)
- `--preset medium` — tốc độ encode x264 (`veryfast` nhanh hơn)
- `--dry-run` — chỉ in lệnh ffmpeg đầy đủ để xem hoặc chạy tay

Các thông số (biên độ zoom, độ rung, độ đậm vệt sáng, ...) nằm ở đầu file `capcut_edit.py`.

**Lưu ý:** vì 5 bộ lọc màu được áp chồng lên nhau theo thứ tự, sau bước 4 (Trắng đen) hình đã mất màu, nên bước 5 (Sáng ấm) cho ra tông đen trắng ngả nâu ấm.
Độ dài video ra ≈ độ dài gốc ÷ 1.25 × 2/3.

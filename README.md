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

Các bộ lọc màu được tính theo đúng ma trận trong đặc tả CSS Filter Effects, áp từng hàm một và clamp sau mỗi hàm giống trình duyệt.

## Cách dùng

Yêu cầu: `ffmpeg`, `ffprobe`, Python 3.

```bash
python3 capcut_edit.py input.mp4 output.mp4
```

Tuỳ chọn:

- `--fit blur` / `--fit crop` — cách đưa vào khung 9:16 (mặc định `blur`)
- `--crf 18` — chất lượng x264 (thấp hơn = đẹp hơn, file nặng hơn)
- `--preset medium` — tốc độ encode x264 (`veryfast` nhanh hơn)
- `--dry-run` — chỉ in lệnh ffmpeg đầy đủ để xem hoặc chạy tay

Các thông số (biên độ zoom, độ rung, độ đậm vệt sáng, ...) nằm ở đầu file `capcut_edit.py`.

Các bộ lọc màu 1, 2, 3 được áp chồng lên nhau theo thứ tự.
Độ dài video ra ≈ độ dài gốc ÷ 1.15 × 2/3.

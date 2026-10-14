#!/usr/bin/env python3
"""Áp dụng chuỗi bước edit kiểu CapCut lên video gốc bằng FFmpeg.

Video gốc được dùng làm nền, rồi lần lượt áp dụng đúng thứ tự:

  1. Ngà lạnh      brightness(1.1) saturate(0.8) contrast(1.05) hue-rotate(5deg)
  2. Sắc nét 4K    contrast(1.2) saturate(1.15) brightness(1.05)
  3. Phim điện ảnh contrast(1.15) saturate(0.9) brightness(0.9) sepia(0.2)
  4. (đã bỏ Trắng đen theo bước 14)
  5. Sáng ấm       sepia(0.3) saturate(1.2) brightness(1.05) contrast(1.05)
  6. Pulse Zoom    zoom 1 -> 1.08 -> 1 theo hàm sin, chu kỳ 2s
  7. Gentle Shake  phóng 4% + crop dịch (x, y) theo tổng các hàm sin/cos
  8. Hard Shake    phóng 10%, rung mạnh mỗi 0.5s rồi tắt dần, trục dọc nảy kiểu bounce
  9. Tốc độ 1.25x  (cả hình lẫn tiếng)
 10. Lật ngang     hflip
 11. Cắt nhịp      giữ 2s, bỏ 1s, lặp đến hết video
 12. Light Leaks   vệt sáng / film burn hòa trộn chế độ screen
 13. Khung 9:16    xuất 1080x1920 (mặc định: video ở giữa, nền là chính video làm mờ)
 17. Bóng ma thị giác  bóng trễ phóng to bám theo chuyển động (ghost / afterimage)

Các bộ lọc màu 1-5 được dịch đúng theo đặc tả CSS Filter Effects: mỗi hàm
(brightness, contrast, saturate, hue-rotate, sepia, grayscale) là một bộ lọc
riêng, áp theo đúng thứ tự viết, có clamp sau mỗi hàm giống trình duyệt.

Dùng:  python3 capcut_edit.py input.mp4 output.mp4
"""

import argparse
import json
import math
import os
import shlex
import shutil
import subprocess
import sys

# ----------------------------------------------------------------------------
# Thông số các bước
# ----------------------------------------------------------------------------

COLOR_PRESETS = [
    ("Ngà lạnh", "brightness(1.1) saturate(0.8) contrast(1.05) hue-rotate(5deg)"),
    ("Sắc nét 4K", "contrast(1.2) saturate(1.15) brightness(1.05)"),
    ("Phim điện ảnh", "contrast(1.15) saturate(0.9) brightness(0.9) sepia(0.2)"),
    ("Sáng ấm", "sepia(0.3) saturate(1.2) brightness(1.05) contrast(1.05)"),
]

PULSE_ZOOM_MAX = 0.08      # bước 6: phóng to tối đa 8% (zoom 1 -> 1.08)
PULSE_ZOOM_PERIOD = 2.0    # bước 6: chu kỳ phóng to rồi thu nhỏ (giây)

GENTLE_SHAKE_SCALE = 1.04  # bước 7: phóng 4% để có lề khi rung
HARD_SHAKE_SCALE = 1.10    # bước 8: phóng 10% để có lề khi rung mạnh
HARD_SHAKE_BEAT = 0.5      # bước 8: mỗi phách 0.5s (120 BPM)

SPEED = 1.25               # bước 9

CUT_KEEP = 2.0             # bước 11: giữ 2s
CUT_DROP = 1.0             # bước 11: bỏ 1s

LEAK_OPACITY = 0.65        # bước 12: độ đậm vệt sáng

OUT_W, OUT_H = 1080, 1920  # bước 13: khung 9:16

# Bước 17: mỗi bóng ma = (trễ giây, phóng to, độ đậm, ánh màu r/g/b).
# Bóng gần đậm hơn, bóng xa to hơn và mờ hơn -> vệt bóng loang ra như hào quang.
GHOST_ECHOES = [
    (0.13, 1.05, 0.50, (0.85, 1.00, 1.10)),  # bóng 1: gần, ánh xanh lơ
    (0.27, 1.10, 0.32, (1.05, 0.85, 1.10)),  # bóng 2: xa hơn, to hơn, ánh tím hồng
]
GHOST_RES = 0.5    # bước 17: dựng bóng ma ở 1/2 độ phân giải (nhanh hơn, mềm như sương)
GHOST_BLUR = 2     # bước 17: bán kính boxblur cho bóng ma (tính ở độ phân giải thấp)


# ----------------------------------------------------------------------------
# CSS filter -> FFmpeg
# ----------------------------------------------------------------------------

def _saturate(s):
    return [
        [0.213 + 0.787 * s, 0.715 - 0.715 * s, 0.072 - 0.072 * s],
        [0.213 - 0.213 * s, 0.715 + 0.285 * s, 0.072 - 0.072 * s],
        [0.213 - 0.213 * s, 0.715 - 0.715 * s, 0.072 + 0.928 * s],
    ]


def _hue_rotate(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [
        [0.213 + c * 0.787 - s * 0.213, 0.715 - c * 0.715 - s * 0.715, 0.072 - c * 0.072 + s * 0.928],
        [0.213 - c * 0.213 + s * 0.143, 0.715 + c * 0.285 + s * 0.140, 0.072 - c * 0.072 - s * 0.283],
        [0.213 - c * 0.213 - s * 0.787, 0.715 - c * 0.715 + s * 0.715, 0.072 + c * 0.928 + s * 0.072],
    ]


def _sepia(a):
    k = 1 - min(a, 1.0)
    return [
        [0.393 + 0.607 * k, 0.769 - 0.769 * k, 0.189 - 0.189 * k],
        [0.349 - 0.349 * k, 0.686 + 0.314 * k, 0.168 - 0.168 * k],
        [0.272 - 0.272 * k, 0.534 - 0.534 * k, 0.131 + 0.869 * k],
    ]


def _grayscale(a):
    k = 1 - min(a, 1.0)
    return [
        [0.2126 + 0.7874 * k, 0.7152 - 0.7152 * k, 0.0722 - 0.0722 * k],
        [0.2126 - 0.2126 * k, 0.7152 + 0.2848 * k, 0.0722 - 0.0722 * k],
        [0.2126 - 0.2126 * k, 0.7152 - 0.7152 * k, 0.0722 + 0.9278 * k],
    ]


def _mixer(m):
    names = ["rr", "rg", "rb", "gr", "gg", "gb", "br", "bg", "bb"]
    vals = [v for row in m for v in row]
    return "colorchannelmixer=" + ":".join(f"{n}={v:.6f}" for n, v in zip(names, vals))


def _lut(expr):
    return f"lutrgb=r='{expr}':g='{expr}':b='{expr}'"


def css_filter_to_ffmpeg(css):
    """Chuyển chuỗi CSS filter thành danh sách bộ lọc FFmpeg (giữ nguyên thứ tự)."""
    out = []
    for token in css.split():
        name, arg = token.rstrip(")").split("(")
        if name == "hue-rotate":
            out.append(_mixer(_hue_rotate(float(arg.replace("deg", "")))))
            continue
        v = float(arg[:-1]) / 100 if arg.endswith("%") else float(arg)
        if name == "brightness":
            out.append(_lut(f"clip(val*{v},0,maxval)"))
        elif name == "contrast":
            out.append(_lut(f"clip((val-maxval/2)*{v}+maxval/2,0,maxval)"))
        elif name == "saturate":
            out.append(_mixer(_saturate(v)))
        elif name == "sepia":
            out.append(_mixer(_sepia(v)))
        elif name == "grayscale":
            out.append(_mixer(_grayscale(v)))
        else:
            raise ValueError(f"Không hỗ trợ hàm CSS filter: {name}")
    return out


# ----------------------------------------------------------------------------
# Dựng filtergraph
# ----------------------------------------------------------------------------

def _even(x):
    return int(round(x / 2)) * 2


def build_step17(w, h, fps, inp, out):
    """Bước 17: Bóng ma thị giác.

    Ảnh chính giữ nguyên độ nét; phần "bóng ma" được tính ở 1/2 độ phân giải:
      ref   = ảnh thu nhỏ + làm mềm (không trễ)
      bóng  = ref trễ d khung (tpad nhân bản khung đầu nên không đổi số khung),
              phóng to quanh tâm để loang ra như hào quang
      thêm  = max(0, bóng - ref) * độ đậm * ánh màu
    Các phần "thêm" của từng bóng gộp bằng lighten, phóng lên kích thước gốc rồi
    cộng vào ảnh chính. Chỉ chỗ bóng sáng hơn ảnh hiện tại mới hiện ra: vật sáng
    di chuyển để lại vệt bóng phía sau, cảnh đứng yên gần như giữ nguyên (chỉ còn
    quầng sáng mỏng do phóng to). Mọi blend dùng shortest=1 và lấy nhịp theo ảnh
    chính nên số khung, fps và mốc thời gian không đổi.
    """
    n = len(GHOST_ECHOES)
    gw, gh = _even(w * GHOST_RES), _even(h * GHOST_RES)
    taps = "".join(f"[s17_r{i}][s17_g{i}]" for i in range(n))
    parts = [
        f"[{inp}]split=2[s17_main][s17_src]",
        f"[s17_src]scale={gw}:{gh}:flags=area,boxblur={GHOST_BLUR}:1,split={2 * n}{taps}",
    ]
    for i, (delay, zoom, opacity, (kr, kg, kb)) in enumerate(GHOST_ECHOES):
        d = max(1, int(round(delay * fps)))           # số khung trễ (>= 1)
        cw, ch = _even(gw / zoom), _even(gh / zoom)   # vùng giữa, kéo ra = phóng to
        zoom_f = (f"crop={cw}:{ch}:(iw-ow)/2:(ih-oh)/2,scale={gw}:{gh}:flags=bicubic,"
                  if (cw, ch) != (gw, gh) else "")
        gain = lambda k: min(k * opacity, 1.0)
        parts.append(
            f"[s17_g{i}]tpad=start={d}:start_mode=clone,{zoom_f}format=gbrp[s17_e{i}]"
        )
        # bóng - ref (subtract kẹp về 0), nhân độ đậm và ánh màu bằng LUT
        parts.append(
            f"[s17_e{i}][s17_r{i}]blend=all_mode=subtract:shortest=1,"
            f"lutrgb=r='val*{gain(kr):.4f}':g='val*{gain(kg):.4f}':b='val*{gain(kb):.4f}'"
            f"[s17_d{i}]"
        )
    # gộp các bóng: lấy phần sáng hơn (lighten)
    cur = "s17_d0"
    for i in range(1, n):
        parts.append(f"[{cur}][s17_d{i}]blend=all_mode=lighten:shortest=1[s17_x{i}]")
        cur = f"s17_x{i}"
    parts.append(f"[{cur}]scale={w}:{h}:flags=bicubic,format=gbrp[s17_add]")
    parts.append(f"[s17_main][s17_add]blend=all_mode=addition:shortest=1[{out}]")
    return ";".join(parts)


def build_filtergraph(w, h, fps, has_audio, fit="blur"):
    v = ["format=rgb48le"]

    # Bước 1-5 (bỏ Trắng đen): bộ lọc màu, áp nối tiếp đúng thứ tự.
    for _, css in COLOR_PRESETS:
        v += css_filter_to_ffmpeg(css)

    v.append("format=gbrp")

    # Bước 6: Pulse Zoom. Hệ số zoom z(t) = 1 + A*(1 - cos(2*pi*t/T))/2 dao động
    # mượt giữa 1 và 1+A. perspective lấy vùng giữa nguồn kéo ra toàn khung với
    # nội suy subpixel nên không bị giật như zoompan.
    t = f"(in/{fps})"
    z = f"(1+{PULSE_ZOOM_MAX}*(1-cos(2*PI*{t}/{PULSE_ZOOM_PERIOD}))/2)"
    mx, my = f"(W/2-W/(2*{z}))", f"(H/2-H/(2*{z}))"
    v.append(
        "perspective="
        f"x0='{mx}':y0='{my}':x1='W-{mx}':y1='{my}':"
        f"x2='{mx}':y2='H-{my}':x3='W-{mx}':y3='H-{my}':"
        "interpolation=cubic:eval=frame"
    )

    # Bước 7: Gentle Shake. Phóng to nhẹ rồi crop lại kích thước gốc, vị trí crop
    # là tổng các sin/cos với tần số không chia hết cho nhau -> chuyển động hỗn
    # loạn nhưng mượt.
    gw, gh = _even(w * GENTLE_SHAKE_SCALE), _even(h * GENTLE_SHAKE_SCALE)
    v.append(f"scale={gw}:{gh}:flags=bicubic")
    v.append(
        f"crop={w}:{h}:"
        "x='(iw-ow)/2*(1+0.6*sin(2*PI*1.3*t)+0.3*sin(2*PI*2.7*t+1.1))':"
        "y='(ih-oh)/2*(1+0.6*cos(2*PI*1.1*t+0.5)+0.3*sin(2*PI*3.1*t+2.3))'"
    )

    # Bước 8: Hard Shake / Bounce. Mỗi phách tạo một cú rung mạnh tần số cao,
    # biên độ tắt dần theo exp, trục y nảy lên kiểu bounce.
    hw, hh = _even(w * HARD_SHAKE_SCALE), _even(h * HARD_SHAKE_SCALE)
    env = f"exp(-9*mod(t,{HARD_SHAKE_BEAT}))"
    v.append(f"scale={hw}:{hh}:flags=bicubic")
    v.append(
        f"crop={w}:{h}:"
        f"x='(iw-ow)/2*(1+0.95*{env}*sin(2*PI*14*t))':"
        f"y='(ih-oh)/2*(1-0.95*{env}*abs(cos(2*PI*9*t)))'"
    )

    # Bước 9: tăng tốc 1.25x, giữ nguyên fps gốc.
    v.append(f"setpts=PTS/{SPEED}")
    v.append(f"fps={fps}")

    # Bước 10: lật ngang.
    v.append("hflip")

    # Bước 11: giữ 2s, bỏ 1s, lặp lại đến hết video.
    cycle = CUT_KEEP + CUT_DROP
    keep = f"lt(mod(t+0.000001,{cycle}),{CUT_KEEP})"
    v.append(f"select='{keep}'")
    v.append("setpts='round(N/(FRAME_RATE*TB))'")
    v.append("format=gbrp")

    graph = ["[0:v]" + ",".join(v) + "[base]"]

    # Bước 12: Light Leaks / Film Burn. Sinh vệt sáng ở độ phân giải thấp bằng
    # geq (2 đốm sáng cam/đỏ trôi chậm + chớp cháy phim mỗi 6s), phóng lên cho
    # mềm rồi hòa trộn screen lên video.
    lw, lh = 192, _even(192 * h / w)
    g1 = "exp(-(pow(X-W*(0.5+0.6*sin(0.37*T)),2)+pow(Y-H*(0.5+0.5*sin(0.53*T+1)),2))/(2*pow(0.30*W,2)))"
    g2 = "exp(-(pow(X-W*(0.5+0.6*cos(0.29*T+2)),2)+pow(Y-H*(0.5+0.5*sin(0.41*T)),2))/(2*pow(0.25*W,2)))"
    edge = "exp(-X/(0.18*W))"  # vệt sáng hắt vào từ mép trái
    flash = "exp(-pow(mod(T,6)-0.6,2)/0.04)"
    pulse = "(0.55+0.45*sin(0.8*T))"

    def chan(a, b, c, f):
        return f"255*clip({pulse}*({a}*{g1}+{b}*{g2}+{c}*{edge})+{f}*{flash},0,1)"

    leak = (
        f"color=c=black:s={lw}x{lh}:r={fps},format=gbrp,"
        f"geq=r='{chan(1.0, 1.0, 0.9, 0.95)}':"
        f"g='{chan(0.55, 0.25, 0.45, 0.70)}':"
        f"b='{chan(0.15, 0.10, 0.10, 0.35)}',"
        f"scale={w}:{h}:flags=bicubic,format=gbrp[leak]"
    )
    graph.append(leak)
    graph.append(
        f"[base][leak]blend=all_mode=screen:all_opacity={LEAK_OPACITY}:shortest=1[edited]"
    )

    # Bước 13: xuất khung 9:16.
    if fit == "crop":
        # Cắt giữa cho kín khung.
        graph.append(
            f"[edited]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase:flags=bicubic,"
            f"crop={OUT_W}:{OUT_H},format=gbrp[s13]"
        )
    else:
        # Giữ trọn khung hình ở giữa, phần trống phủ bằng chính video phóng to
        # và làm mờ (làm mờ ở 1/4 độ phân giải cho nhanh).
        bw, bh = OUT_W // 4, OUT_H // 4
        graph.append(
            "[edited]split[fg0][bg0];"
            f"[bg0]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
            f"boxblur=12:2,scale={OUT_W}:{OUT_H}:flags=bicubic[bg];"
            f"[fg0]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease:"
            "force_divisible_by=2:flags=bicubic[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2:format=gbrp,format=gbrp[s13]"
        )

    # Bước 17: Bóng ma thị giác.
    graph.append(build_step17(OUT_W, OUT_H, fps, "s13", "s17"))
    graph.append("[s17]format=yuv420p[vout]")

    if has_audio:
        # Bước 9 + 11 cho âm thanh, đồng bộ với hình.
        graph.append(
            f"[0:a]atempo={SPEED},asetnsamples=n=256:p=0,"
            f"aselect='{keep}',asetpts='round(N/(SR*TB))'[aout]"
        )

    return ";".join(graph)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".3gp", ".ts")


def fail(msg):
    print(f"\nLỖI: {msg}", file=sys.stderr)
    sys.exit(1)


def check_input(path):
    """Báo lỗi dễ hiểu nếu file video không tồn tại."""
    if os.path.isfile(path):
        return
    folder = os.path.dirname(os.path.abspath(path))
    try:
        videos = sorted(f for f in os.listdir(folder) if f.lower().endswith(VIDEO_EXTS))
    except OSError:
        videos = []
    msg = f"không tìm thấy file video '{path}' trong thư mục:\n  {folder}\n"
    # Windows hay ẩn đuôi file: đặt tên "input.mp4" thành ra "input.mp4.mp4".
    doubled = [f for f in videos if f.lower().startswith(os.path.basename(path).lower())]
    if doubled:
        msg += f"\nCó file tên gần giống: '{doubled[0]}' (Windows đang ẩn đuôi file). Hãy chạy:\n"
        msg += f'  python capcut_edit.py "{doubled[0]}" output.mp4\n'
    elif videos:
        msg += "\nCác file video có trong thư mục này:\n"
        msg += "".join(f"  - {f}\n" for f in videos[:20])
        msg += f'\nVí dụ chạy:  python capcut_edit.py "{videos[0]}" output.mp4\n'
    else:
        msg += "\nThư mục này không có file video nào. Hãy chép video vào cùng thư mục với\n"
        msg += "capcut_edit.py, hoặc ghi đường dẫn đầy đủ trong ngoặc kép, ví dụ:\n"
        msg += '  python capcut_edit.py "C:\\Users\\Admin\\Videos\\video cua toi.mp4" output.mp4\n'
    fail(msg)


def probe(path):
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        fail(f"ffprobe không đọc được file '{path}' (file hỏng hoặc không phải video).\n"
             f"Chi tiết: {proc.stderr.strip()}")
    streams = json.loads(proc.stdout).get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        fail(f"file '{path}' không có hình (video stream).")
    has_audio = any(s["codec_type"] == "audio" for s in streams)
    num, den = video.get("avg_frame_rate", "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    if not 1 <= fps <= 120:
        fps = 30.0
    return _even(int(video["width"])), _even(int(video["height"])), round(fps, 3), has_audio


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="video gốc")
    ap.add_argument("output", help="video kết quả (.mp4)")
    ap.add_argument("--crf", type=int, default=18, help="chất lượng x264 (thấp = đẹp hơn, mặc định 18)")
    ap.add_argument("--preset", default="medium", help="preset x264 (mặc định medium)")
    ap.add_argument("--fit", choices=["blur", "crop"], default="blur",
                    help="cách đưa vào khung 9:16: blur = video ở giữa, nền mờ (mặc định); "
                         "crop = cắt giữa cho kín khung")
    ap.add_argument("--dry-run", action="store_true", help="chỉ in lệnh ffmpeg, không chạy")
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            fail(f"chưa cài {tool} hoặc chưa có trong PATH. Cài FFmpeg rồi mở lại cửa sổ dòng lệnh.\n"
                 "  Windows:  winget install Gyan.FFmpeg --source winget\n"
                 "  macOS:    brew install ffmpeg")
    check_input(args.input)
    if os.path.abspath(args.input) == os.path.abspath(args.output):
        fail("file kết quả phải khác file gốc.")

    w, h, fps, has_audio = probe(args.input)
    graph = build_filtergraph(w, h, fps, has_audio, args.fit)

    cmd = ["ffmpeg", "-hide_banner", "-y", "-i", args.input,
           "-filter_complex", graph, "-map", "[vout]"]
    if has_audio:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", args.output]

    if args.dry_run:
        print(shlex.join(cmd))
        return 0
    print(f"Input: {w}x{h} @ {fps}fps, audio={'có' if has_audio else 'không'}", file=sys.stderr)
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())

"""Builds ffmpeg command lines. Every segment of a channel is encoded with identical parameters so the
MPEG-TS pieces can be glued into one continuous broadcast."""
import os
import subprocess
import re
import random

from .config import IS_WINDOWS, NO_WINDOW
from .graphics import image_size
from . import branding


def esc(value):
    """Escape a value for use inside an ffmpeg filtergraph option (both escaping levels)."""
    v = str(value).replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
    return "'" + v.replace("'", "'\\''") + "'"


def parse_res(res):
    try:
        w, h = (int(x) for x in str(res).lower().split("x"))
        return w - w % 2, h - h % 2
    except Exception:
        return 1280, 720


NVENC_PRESETS = {"ultrafast": "p1", "superfast": "p1", "veryfast": "p2", "faster": "p3", "fast": "p4",
                 "medium": "p5", "slow": "p6", "slower": "p7", "veryslow": "p7"}


TAGS = "setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709"
COLOR_ARGS = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]


def encoder_args(st):
    """Returns (args before inputs, filter tail, encoder args)."""
    enc = st.get("video_encoder") or "libx264"
    fps = int(st.get("framerate") or 30)
    br = int(st.get("video_bitrate_kbps") or 4000)
    preset = st.get("encoder_preset") or "veryfast"
    g = str(fps * 2)
    rate = ["-b:v", f"{br}k", "-maxrate", f"{br}k", "-bufsize", f"{br * 2}k"]
    pre, tail = [], ""
    if enc == "h264_nvenc":
        args = ["-c:v", "h264_nvenc", "-preset", NVENC_PRESETS.get(preset, preset if preset.startswith("p") else "p4"),
                "-rc", "cbr", "-profile:v", "high", "-g", g, "-forced-idr", "1"] + rate
    elif enc == "h264_qsv":
        tail = ",format=nv12"
        args = ["-c:v", "h264_qsv", "-preset", preset if preset in NVENC_PRESETS else "veryfast",
                "-profile:v", "high", "-g", g] + rate
    elif enc == "h264_amf":
        tail = ",format=nv12"
        args = ["-c:v", "h264_amf", "-usage", "transcoding", "-quality", "speed", "-rc", "cbr",
                "-profile:v", "high", "-g", g] + rate
    elif enc == "h264_vaapi":
        pre = ["-vaapi_device", st.get("vaapi_device") or "/dev/dri/renderD128"]
        tail = ",format=nv12,hwupload"
        args = ["-c:v", "h264_vaapi", "-profile:v", "high", "-g", g] + rate
    elif enc == "h264_videotoolbox":
        args = ["-c:v", "h264_videotoolbox", "-realtime", "1", "-profile:v", "high", "-g", g] + rate
    else:
        args = ["-c:v", "libx264", "-preset", preset, "-profile:v", "high", "-level:v", "4.1", "-g", g,
                "-keyint_min", g, "-sc_threshold", "0", "-x264-params", "repeat-headers=1"] + rate
    return pre, tail, args + COLOR_ARGS


def _clock_text(fmt):
    if fmt == "24h":
        return "%{localtime:%H\\:%M}"
    if fmt == "24h_sec":
        return "%{localtime:%H\\:%M\\:%S}"
    hour = "%#I" if IS_WINDOWS else "%-I"
    if fmt == "12h_plain":
        return "%{localtime:" + hour + "\\:%M}"
    if fmt == "12h_sec":
        return "%{localtime:" + hour + "\\:%M\\:%S %p}"
    return "%{localtime:" + hour + "\\:%M %p}"


def _ffcolor(value, default):
    v = (value or "").strip().lstrip("#")
    return "0x" + v.lower() if len(v) == 6 and all(c in "0123456789abcdefABCDEF" for c in v) else default


def _num(v, default, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def clock_filter(clock, font, fs, x, y):
    """drawtext for the corner clock: font, colour, text opacity, outline, shadow and the bar behind it."""
    op = _num(clock.get("opacity", 100), 100, 5, 100) / 100
    bg = _num(clock.get("bg_opacity", 35), 35, 0, 100) / 100
    color = _ffcolor(clock.get("color"), "white")
    out = [f"drawtext=fontfile={esc(font)}:text={esc(_clock_text(clock.get('format', '12h')))}",
           f"fontsize={fs}:fontcolor={color}@{op:.2f}:x={x}:y={y}"]
    outline = clock.get("outline", "none")
    if outline in ("thin", "thick"):
        bw = max(1, round(fs * (0.045 if outline == "thin" else 0.09)))
        out.append(f"borderw={bw}:bordercolor=black@{min(1.0, op * 0.95):.2f}")
    if clock.get("shadow", True):
        sh = max(1, round(fs / 22))
        out.append(f"shadowx={sh}:shadowy={sh}:shadowcolor=black@{0.6 * op:.2f}")
    if bg > 0:
        out.append(f"box=1:boxcolor=black@{bg:.2f}:boxborderw={max(4, fs // 4)}")
    return ":".join(out)


def _corner(pos, m, w_expr, h_expr):
    """x/y expressions for a corner, given overlay/drawtext width & height expressions."""
    x = str(m) if "left" in pos else f"W-{w_expr}-{m}"
    y = str(m) if "top" in pos else f"H-{h_expr}-{m}"
    return x, y


_music_len = {}


def music_length(ffmpeg, path):
    """Seconds of audio in a music file (cached; None if unknown)."""
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    if key not in _music_len:
        dur = None
        try:
            r = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", path], capture_output=True, text=True,
                               timeout=15, creationflags=NO_WINDOW, errors="replace")
            m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
            if m:
                dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        except Exception:
            pass
        if len(_music_len) > 2000:
            _music_len.clear()
        _music_len[key] = dur
    return _music_len[key]


class Builder:
    def __init__(self, settings, ffmpeg_path, fonts):
        self.st = settings
        self.ffmpeg = ffmpeg_path
        self.fonts = fonts            # graphics.Fonts
        self.W, self.H = parse_res(settings.get("resolution"))
        self.fps = int(settings.get("framerate") or 30)
        self.clock_font = None        # callable(ch) -> (font file, size scale); set by App.builder()

    def music_start(self, path):
        """Start music somewhere random in the song (never in its last minute), so a bed doesn't always open the
        same way. Returns input options for ffmpeg."""
        length = music_length(self.ffmpeg, path)
        if not length or length <= 75:
            return []
        return ["-ss", f"{random.uniform(0, length - 60):.2f}"]

    # ------------------------------------------------------------ overlays
    def _overlay_graph(self, ch, base_label, logo_path, up_next=None):
        """Returns (graph fragment, output label, uses_logo_input)."""
        W, H = self.W, self.H
        m = round(H * 0.045)
        parts, cur = [], base_label
        logo_cfg = ch.get("logo") or {}
        lw = lh = 0
        logo_pos = logo_cfg.get("position", "top-right")
        if logo_path and os.path.isfile(logo_path):
            iw, ih = image_size(logo_path)
            lw = max(16, int(W * float(logo_cfg.get("size_percent") or 12) / 100)) // 2 * 2
            lh = max(2, int(lw * ih / max(1, iw))) // 2 * 2
            if lh > H * 0.3:
                lh = int(H * 0.3) // 2 * 2
                lw = max(2, int(lh * iw / max(1, ih))) // 2 * 2
            op = max(0.05, min(1.0, float(logo_cfg.get("opacity") or 0.85)))
            x = str(m) if "left" in logo_pos else str(W - lw - m)
            y = str(m) if "top" in logo_pos else str(H - lh - m)
            parts.append(f"[1:v]format=rgba,scale={lw}:{lh},colorchannelmixer=aa={op:.2f}[lg]")
            parts.append(f"[{cur}][lg]overlay={x}:{y}:format=auto[ov]")
            cur = "ov"
        texts = []
        clock = ch.get("clock") or {}
        if clock.get("enabled"):
            pos = clock.get("position", "top-left")
            font, scale = self.clock_font(ch) if self.clock_font else (self.fonts.path_for("", True), 1.0)
            fs = max(10, int(H * float(clock.get("size_percent") or 4.5) / 100 * scale))
            x, y = _corner(pos, m, "tw", "th")
            if lw and pos == logo_pos:  # same corner as the logo: stack the clock beside it
                gap = int(m * 0.4)
                y = f"{m + lh + gap}" if "top" in pos else f"H-th-{m + lh + gap}"
            if font:
                texts.append(clock_filter(clock, font, fs, x, y))
        if up_next:
            t0, t1, label = up_next[:3]
            style = up_next[3] if len(up_next) > 3 else {}
            fs = max(12, int(H * 0.042))
            font = style.get("font") or self.fonts.path_for(label, True)
            box = _ffcolor(style.get("box"), "0x1d4ed8")
            fg = _ffcolor(style.get("fg"), "white")
            if font:
                x = str(m) if logo_pos != "bottom-left" or not lw else str(m + lw + m)
                alpha = (f"if(lt(t,{t0:.2f}),0,if(lt(t,{t0 + 0.6:.2f}),(t-{t0:.2f})/0.6,"
                         f"if(lt(t,{t1 - 0.6:.2f}),1,if(lt(t,{t1:.2f}),({t1:.2f}-t)/0.6,0))))")
                texts.append(
                    f"drawtext=fontfile={esc(font)}:expansion=none:text={esc(label)}:fontsize={fs}"
                    f":fontcolor={fg}:x={x}:y=H-th-{int(m * 1.6)}:box=1:boxcolor={box}@0.9"
                    f":boxborderw={fs // 2}:enable={esc(f'between(t,{t0:.2f},{t1:.2f})')}:alpha={esc(alpha)}")
        if texts:
            parts.append(f"[{cur}]" + ",".join(texts) + "[tx]")
            cur = "tx"
        return parts, cur, bool(lw)

    # ------------------------------------------------------------ commands
    def segment(self, ch, *, source=None, image=None, concat=None, duration, offset=0.0, ts_offset=0.0, audio_index=None,
                has_audio=True, hdr=False, logo_path=None, music=None, up_next=None, headers=None, preview=False,
                initial_burst=0.0, subtitle=None):
        """source = media URL/path, or image = slate PNG. Produces MPEG-TS on stdout (or one JPEG if preview)."""
        st, W, H, fps = self.st, self.W, self.H, self.fps
        pre, vtail, venc = encoder_args(st)
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"] + (pre if not preview else [])
        re_ = [] if preview else ["-re"]
        # input 0: program, slate image, or a bumper (sequence of card images)
        if concat:
            # one still frame per card: pace with the realtime filter after fps (see below), not -re, so frames
            # flow out steadily instead of in bursts at each card change
            cmd += ["-f", "concat", "-safe", "0", "-i", str(concat)]
        elif image:
            cmd += ["-loop", "1", "-framerate", str(fps)] + re_ + ["-i", str(image)]
        else:
            if source.startswith("http"):
                if headers:
                    cmd += ["-headers", headers]
                cmd += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "4"]
            if offset > 0.5:
                cmd += ["-ss", f"{offset:.3f}"]
            if initial_burst and re_:
                cmd += ["-readrate_initial_burst", f"{initial_burst:.1f}"]
            cmd += ["-thread_queue_size", "1024"] + re_ + ["-i", source]
        n_in = 1
        # input 1: logo
        if logo_path and os.path.isfile(logo_path):
            cmd += ["-loop", "1", "-i", str(logo_path)]
            n_in += 1
        else:
            logo_path = None
        # next input: audio bed for slates / silent media
        bed_idx = n_in
        still = bool(image or concat)
        need_bed = still or not has_audio
        if need_bed:
            if music and os.path.isfile(music):
                cmd += ["-stream_loop", "-1"] + self.music_start(music) + re_ + ["-i", music]
            else:
                cmd += ["-f", "lavfi"] + re_ + ["-i", "anullsrc=r=48000:cl=stereo"]
        # ---- filtergraph
        if still:
            chain = [f"scale={W}:{H}:force_original_aspect_ratio=decrease:out_color_matrix=bt709:out_range=tv",
                     "format=yuv420p", f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
                     "setsar=1", f"fps={fps}", "format=yuv420p"] + (["realtime"] if concat and not preview else [])
            graph = ["[0:v]" + ",".join(chain) + "[base]"]
        else:
            chain = []
            if st.get("deinterlace", True):
                chain.append("bwdif=mode=send_frame:parity=auto:deint=interlaced")
            if hdr and st.get("tonemap_hdr", True):
                chain.append("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                             "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv")
            chain += [f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=bicubic:out_color_matrix=bt709:out_range=tv",
                      "format=yuv420p", f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black", "setsar=1"]
            sub = subtitle or {}
            if sub.get("kind") == "text":
                # libass draws at the output size. The input was seeked, so shift timestamps to the file's own
                # clock while the subtitles are drawn, then back.
                off = max(0.0, float(offset or 0))
                opts = f"filename={esc(sub['file'])}"
                if sub.get("fontsdir"):
                    opts += f":fontsdir={esc(sub['fontsdir'])}"
                if sub.get("style"):
                    opts += f":force_style={esc(sub['style'])}"
                chain += [f"setpts=PTS+{off:.3f}/TB", f"subtitles={opts}", f"setpts=PTS-{off:.3f}/TB"]
            chain.append(f"fps={fps}")
            if sub.get("kind") == "image":
                # bitmap subtitles (Blu-ray PGS, DVD VobSub, DVB) come from the file itself: scale to the picture, overlay
                graph = ["[0:V:0]" + ",".join(chain) + "[vid]",
                         f"[0:s:{int(sub['rel'])}]scale={W}:{H}:force_original_aspect_ratio=decrease[subs]",
                         "[vid][subs]overlay=(W-w)/2:(H-h)/2:eof_action=pass:format=auto,format=yuv420p[base]"]
            else:
                graph = ["[0:V:0]" + ",".join(chain) + "[base]"]
        ov, cur, _ = self._overlay_graph(ch, "base", logo_path, up_next)
        graph += ov
        # identical colour tags on every segment, so the H.264 headers never change mid-stream
        graph.append(f"[{cur}]format=yuv420p,{TAGS}{'' if preview else vtail}[v]")
        a_in = f"{bed_idx}:a" if need_bed else (f"0:a:{audio_index}" if audio_index is not None else "0:a:0")
        anorm = ",loudnorm=I=-16:TP=-1.5:LRA=11" if ch.get("normalize_audio") and not still else ""
        if still and music and os.path.isfile(music) and duration > 3:
            anorm += f",afade=t=in:d=0.4,afade=t=out:st={max(0.0, duration - 1.2):.2f}:d=1.2"
        if not preview:
            graph.append(f"[{a_in}]aresample=48000:async=1:first_pts=0{anorm},"
                         f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a]")
        cmd += ["-filter_complex", ";".join(graph), "-map", "[v]"]
        if preview:
            cmd += ["-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "-q:v", "3", "pipe:1"]
            return cmd
        cmd += ["-map", "[a]", "-t", f"{duration:.3f}"] + venc + [
            "-c:a", "aac", "-b:a", f"{int(st.get('audio_bitrate_kbps') or 192)}k", "-ar", "48000", "-ac", "2",
            "-max_muxing_queue_size", "4096", "-flush_packets", "1",
            "-f", "mpegts", "-mpegts_service_id", "1", "-metadata", f"service_provider={branding.name()}",
            "-metadata", f"service_name={ch.get('name', 'Channel')}",
            "-output_ts_offset", f"{ts_offset:.3f}", "pipe:1"]
        return cmd

    def weather(self, ch, crawl_file=None, crawl_font=None, crawl_y=0, crawl_x0=0, crawl_size=24, crawl_color="white",
                crawl_speed=110, label=None, label_color="black", label_box="yellow", band=None, band_color="black",
                music=None, ts_offset=0.0):
        """Weather channel: full-frame raw RGB frames at 1 fps on stdin, plus a smoothly scrolling crawl drawn by
        ffmpeg (the text file is re-read every second, so it can change without a restart)."""
        st, W, H, fps = self.st, self.W, self.H, self.fps
        pre, vtail, venc = encoder_args(st)
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"] + pre + [
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", "1",
            "-thread_queue_size", "64", "-i", "pipe:0"]
        if music and os.path.isfile(music):
            cmd += ["-stream_loop", "-1"] + self.music_start(music) + ["-re", "-i", music]
        else:
            cmd += ["-f", "lavfi", "-re", "-i", "anullsrc=r=48000:cl=stereo"]
        chain = [f"fps={fps}"]
        if crawl_file and crawl_font:
            spd = max(20, int(crawl_speed * H / 720))
            chain.append(
                f"drawtext=fontfile={esc(crawl_font)}:textfile={esc(crawl_file)}:reload={fps}:expansion=none"
                f":fontsize={crawl_size}:fontcolor={crawl_color}:y={crawl_y}-th/2"
                f":x={esc(f'{W}-mod(t*{spd},{W}-{crawl_x0}+tw)')}")
            if band:      # cover the crawl where it slides off to the left, under the label
                chain.append(f"drawbox=x=0:y={band[0]}:w={crawl_x0}:h={band[1] - band[0]}:color={band_color}:t=fill")
            if label:
                chain.append(
                    f"drawtext=fontfile={esc(crawl_font)}:text={esc(label)}:expansion=none:fontsize={crawl_size}"
                    f":fontcolor={label_color}:x={int(crawl_x0 - crawl_size * 0.6)}-tw:y={crawl_y}-th/2"
                    f":box=1:boxcolor={label_box}:boxborderw={max(6, crawl_size // 2)}")
        v = "[0:v]" + ",".join(chain) + f",scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,{TAGS}{vtail}[v]"
        a = "[1:a]aresample=48000:async=1,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a]"
        cmd += ["-filter_complex", v + ";" + a, "-map", "[v]", "-map", "[a]"] + venc + [
            "-c:a", "aac", "-b:a", f"{int(st.get('audio_bitrate_kbps') or 192)}k",
            "-flush_packets", "1", "-f", "mpegts", "-mpegts_service_id", "1",
            "-metadata", f"service_name={ch.get('name', 'Weather')}", "-output_ts_offset", f"{ts_offset:.3f}", "pipe:1"]
        return cmd

    def guide(self, ch, canvas_h, head_h, body_h, rows_h, scroll, speed, music=None, ts_offset=0.0):
        """Guide channel: raw RGB frames at 1 fps on stdin, scrolled + encoded by ffmpeg."""
        st, W, H, fps = self.st, self.W, self.H, self.fps
        pre, vtail, venc = encoder_args(st)
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"] + pre + [
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{canvas_h}", "-framerate", "1",
            "-thread_queue_size", "64", "-i", "pipe:0"]
        if music and os.path.isfile(music):
            cmd += ["-stream_loop", "-1"] + self.music_start(music) + ["-re", "-i", music]
        else:
            cmd += ["-f", "lavfi", "-re", "-i", "anullsrc=r=48000:cl=stereo"]
        spd = max(5, int(speed * H / 720))
        if scroll:
            v = (f"[0:v]fps={fps},split=2[h][b];[h]crop={W}:{head_h}:0:0[hh];"
                 f"[b]crop={W}:{body_h}:0:{head_h}+mod(t*{spd}\\,{rows_h})[bb];"
                 f"[hh][bb]vstack=2,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,{TAGS}{vtail}[v]")
        else:
            v = f"[0:v]fps={fps},crop={W}:{H}:0:0,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,{TAGS}{vtail}[v]"
        a = "[1:a]aresample=48000:async=1,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a]"
        cmd += ["-filter_complex", v + ";" + a, "-map", "[v]", "-map", "[a]"] + venc + [
            "-c:a", "aac", "-b:a", f"{int(st.get('audio_bitrate_kbps') or 192)}k",
            "-flush_packets", "1", "-f", "mpegts", "-mpegts_service_id", "1",
            "-metadata", f"service_name={ch.get('name', 'Guide')}", "-output_ts_offset", f"{ts_offset:.3f}", "pipe:1"]
        return cmd

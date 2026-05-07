import os
import subprocess
import uuid
import json


ALLOWED_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".mkv",
    ".avi",
}


_FFMPEG_ENCODERS_CACHE: str | None = None


def _ffmpeg_encoders_text() -> str:
    global _FFMPEG_ENCODERS_CACHE
    if _FFMPEG_ENCODERS_CACHE is not None:
        return _FFMPEG_ENCODERS_CACHE

    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _FFMPEG_ENCODERS_CACHE = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except Exception:
        _FFMPEG_ENCODERS_CACHE = ""

    return _FFMPEG_ENCODERS_CACHE


def _pick_h264_encoder(*, prefer_hardware: bool = True) -> str:
    """
    Choose the fastest available H.264 encoder.

    Hardware encoders (when present) are dramatically faster than libx264.
    """
    enc_txt = _ffmpeg_encoders_text().lower()

    if prefer_hardware:
        for enc in ("h264_nvenc", "h264_qsv", "h264_amf"):
            if enc in enc_txt:
                return enc

    return "libx264"


def _run_ffmpeg(args: list[str]) -> None:
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "ffmpeg failed").strip())


def _run_ffprobe_json(input_path: str) -> dict:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            input_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "ffprobe failed").strip())
    try:
        return json.loads(proc.stdout or "{}")
    except Exception as e:
        raise RuntimeError(f"ffprobe returned invalid JSON: {e}")


def _get_duration_seconds(input_path: str) -> float:
    data = _run_ffprobe_json(input_path)
    fmt = data.get("format") or {}
    dur = fmt.get("duration")
    try:
        dur_f = float(dur)
    except Exception:
        dur_f = 0.0
    if dur_f <= 0:
        raise RuntimeError("Could not determine video duration.")
    return dur_f


def compress_video_for_sms(
    input_path: str,
    *,
    max_megabytes: int = 7,
    max_seconds: int = 8,
    max_width: int = 480,
    preserve_length: bool = False,
) -> str:
    """
    Create a smaller MP4 suitable for texting.

    Notes:
    - This is a best-effort "SMS/MMS friendly" export (H.264/AAC, yuv420p).
    - By default we cap duration + resolution and target a size budget via bitrate.
    - If preserve_length=True, we keep full duration and compute the bitrate budget from the source duration.
    """
    if max_megabytes <= 0:
        raise ValueError("max_megabytes must be > 0")
    if not preserve_length and max_seconds <= 0:
        raise ValueError("max_seconds must be > 0")
    if max_width <= 0:
        raise ValueError("max_width must be > 0")

    base, _ = os.path.splitext(input_path)
    unique = uuid.uuid4().hex[:8]
    output_path = f"{base}_sms_{unique}.mp4"

    # Bitrate budget: bits = MB * 8e6. We reserve some headroom for audio.
    # When preserving length, use the full duration to compute the per-second budget.
    seconds_budget = float(max_seconds)
    if preserve_length:
        seconds_budget = _get_duration_seconds(input_path)

    total_bits_per_sec = int((max_megabytes * 8_000_000) / max(seconds_budget, 0.1))
    audio_bps = 48_000
    video_bps = max(200_000, total_bits_per_sec - audio_bps)

    # Scale down while preserving aspect ratio.
    # If already narrower than max_width, keep original width.
    scale_filter = f"scale='min({max_width},iw)':-2"

    # Prioritize speed over quality: single-pass encode and low FPS.
    # This may miss the size target by a bit on some content, but will run far faster.
    v_encoder = _pick_h264_encoder(prefer_hardware=True)
    base_args = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        input_path,
        "-vf",
        scale_filter,
        "-r",
        "15",
        "-b:v",
        str(video_bps),
        "-maxrate",
        str(video_bps),
        "-bufsize",
        str(video_bps * 2),
        "-c:a",
        "aac",
        "-b:a",
        "48k",
        "-ac",
        "1",
        "-movflags",
        "+faststart",
    ]

    if not preserve_length:
        base_args[base_args.index(input_path) + 1: base_args.index(input_path) + 1] = ["-t", str(max_seconds)]

    common = base_args + ["-c:v", v_encoder]
    if v_encoder == "libx264":
        common += [
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
        ]
    else:
        # Best-effort knobs for speed on common HW encoders.
        # (If unsupported, ffmpeg will error; fall back to libx264.)
        try:
            if v_encoder == "h264_nvenc":
                common += ["-preset", "p1"]
            elif v_encoder == "h264_qsv":
                common += ["-preset", "veryfast"]
            elif v_encoder == "h264_amf":
                common += ["-quality", "speed"]
        except Exception:
            pass

    try:
        _run_ffmpeg(common + [output_path])
    except Exception:
        # Fallback to CPU x264 if a HW encoder is present but unusable at runtime.
        cpu_args = (
            base_args
            + [
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
            ]
            + [output_path]
        )
        _run_ffmpeg(cpu_args)

    return output_path


def compress_video_quality(
    input_path: str,
    *,
    crf: int = 28,
    preset: str = "veryfast",
) -> str:
    """
    Re-encode to a reasonably high-quality MP4 while preserving full duration.

    Notes:
    - Preserves original length (no -t trim).
    - Does not downscale or force FPS; the source determines those.
    - Uses CRF-based x264 encode (smaller file while keeping quality "for the most part").
    """
    if crf < 0 or crf > 51:
        raise ValueError("crf must be between 0 and 51")

    base, _ = os.path.splitext(input_path)
    unique = uuid.uuid4().hex[:8]
    output_path = f"{base}_quality_{unique}.mp4"

    v_encoder = _pick_h264_encoder(prefer_hardware=True)

    # For speed: prefer hardware H.264 encoders when available; otherwise use a fast x264 preset.
    video_args: list[str] = ["-c:v", v_encoder]
    if v_encoder == "libx264":
        video_args += ["-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
    else:
        # Use bitrate-based control on HW encoders for broad compatibility.
        # Bump bitrate to improve quality while staying very fast.
        video_args += ["-b:v", "2500k", "-maxrate", "3000k", "-bufsize", "6000k"]
        if v_encoder == "h264_nvenc":
            video_args += ["-preset", "p1"]
        elif v_encoder == "h264_qsv":
            video_args += ["-preset", "veryfast"]
        elif v_encoder == "h264_amf":
            video_args += ["-quality", "speed"]

    args = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        input_path,
        *video_args,
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        output_path,
    ]

    try:
        _run_ffmpeg(args)
    except Exception:
        if v_encoder != "libx264":
            # Retry on CPU x264 for compatibility.
            fallback_args = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-i",
                input_path,
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                output_path,
            ]
            _run_ffmpeg(fallback_args)
        else:
            raise

    return output_path


def compress_video_message_fast(
    input_path: str,
    *,
    max_width: int = 720,
    fps: int = 24,
    crf: int = 28,
    preset: str = "veryfast",
    video_bps: int = 2_500_000,
    audio_bps: int = 96_000,
) -> str:
    """
    Fast, full-length, messaging-friendly MP4 export.

    Goals:
    - Preserve full duration
    - Prioritize speed (hardware H.264 when available)
    - Keep compatibility (H.264 + AAC, yuv420p, faststart)
    - Keep quality decent by downscaling and using a moderate bitrate/CRF
    """
    if max_width <= 0:
        raise ValueError("max_width must be > 0")
    if fps <= 0:
        raise ValueError("fps must be > 0")
    if crf < 0 or crf > 51:
        raise ValueError("crf must be between 0 and 51")
    if video_bps <= 0:
        raise ValueError("video_bps must be > 0")
    if audio_bps < 0:
        raise ValueError("audio_bps must be >= 0")

    base, _ = os.path.splitext(input_path)
    unique = uuid.uuid4().hex[:8]
    output_path = f"{base}_message_{unique}.mp4"

    # Downscale while preserving aspect ratio, keep even dimensions.
    scale_filter = f"scale='min({max_width},iw)':-2"

    v_encoder = _pick_h264_encoder(prefer_hardware=True)

    video_args: list[str] = ["-c:v", v_encoder]
    if v_encoder == "libx264":
        video_args += ["-preset", preset, "-crf", str(crf)]
    else:
        # Bitrate-based control is broadly supported across HW encoders.
        video_args += [
            "-b:v",
            str(video_bps),
            "-maxrate",
            str(int(video_bps * 1.2)),
            "-bufsize",
            str(int(video_bps * 2.0)),
        ]
        if v_encoder == "h264_nvenc":
            video_args += ["-preset", "p1"]
        elif v_encoder == "h264_qsv":
            video_args += ["-preset", "veryfast"]
        elif v_encoder == "h264_amf":
            video_args += ["-quality", "speed"]

    audio_args: list[str] = ["-c:a", "aac"]
    if audio_bps == 0:
        audio_args = ["-an"]
    else:
        audio_args += ["-b:a", str(audio_bps), "-ac", "2"]

    args = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        input_path,
        "-vf",
        scale_filter,
        "-r",
        str(fps),
        *video_args,
        "-pix_fmt",
        "yuv420p",
        *audio_args,
        "-movflags",
        "+faststart",
        output_path,
    ]

    try:
        _run_ffmpeg(args)
    except Exception:
        if v_encoder != "libx264":
            # Retry on CPU x264 for compatibility.
            fallback_args = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-i",
                input_path,
                "-vf",
                scale_filter,
                "-r",
                str(fps),
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                *audio_args,
                "-movflags",
                "+faststart",
                output_path,
            ]
            _run_ffmpeg(fallback_args)
        else:
            raise

    return output_path


def compress_video_to_target_size(
    input_path: str,
    *,
    target_megabytes: float = 2.5,
    target_height: int = 360,
    prefer_h265: bool = False,
    preset: str = "ultrafast",
    audio_bps: int = 48_000,
    max_attempts: int = 1,
) -> str:
    """
    Best-effort "keep full duration" export that tries to hit a target size.

    Pipeline:
    - Keep full duration (no trim)
    - Downscale to target_height (360/480 recommended), preserving aspect ratio
    - Try H.265 (libx265) when available, otherwise H.264 (libx264)
    - Tune bitrate iteratively until the output is <= target size
    """
    if target_megabytes <= 0:
        raise ValueError("target_megabytes must be > 0")
    if target_height not in (360, 480):
        raise ValueError("target_height must be 360 or 480")
    if audio_bps < 0:
        raise ValueError("audio_bps must be >= 0")
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    duration = _get_duration_seconds(input_path)
    target_bytes = int(target_megabytes * 1024 * 1024)

    # bitrate budget: total_bits_per_sec = target_bytes * 8 / duration
    total_bps = int((target_bytes * 8) / max(duration, 0.1))
    video_bps = max(150_000, total_bps - audio_bps)

    base, _ = os.path.splitext(input_path)
    unique = uuid.uuid4().hex[:8]
    output_path = f"{base}_target_{unique}.mp4"

    # scale to target height, keep aspect ratio, ensure even dimensions
    scale_filter = f"scale=-2:{target_height}"

    def _encode(codec: str, v_bps: int) -> None:
        # For speed, opportunistically use HW encoders for H.264.
        if codec == "libx264":
            v_codec = _pick_h264_encoder(prefer_hardware=True)
        else:
            v_codec = codec

        v_args: list[str] = ["-c:v", v_codec]
        if v_codec == "libx264":
            v_args += ["-preset", preset, "-b:v", str(v_bps), "-maxrate", str(v_bps), "-bufsize", str(v_bps * 2)]
        else:
            v_args += ["-b:v", str(v_bps), "-maxrate", str(v_bps), "-bufsize", str(v_bps * 2)]
            if v_codec == "h264_nvenc":
                v_args += ["-preset", "p1"]
            elif v_codec == "h264_qsv":
                v_args += ["-preset", "veryfast"]
            elif v_codec == "h264_amf":
                v_args += ["-quality", "speed"]

        args = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-i",
            input_path,
            "-vf",
            scale_filter,
            *v_args,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            str(audio_bps),
            "-ac",
            "1",
            "-movflags",
            "+faststart",
            output_path,
        ]

        try:
            _run_ffmpeg(args)
        except Exception:
            if v_codec != "libx264":
                # Retry on CPU x264 for compatibility.
                fallback_args = [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-i",
                    input_path,
                    "-vf",
                    scale_filter,
                    "-c:v",
                    "libx264",
                    "-preset",
                    preset,
                    "-b:v",
                    str(v_bps),
                    "-maxrate",
                    str(v_bps),
                    "-bufsize",
                    str(v_bps * 2),
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    str(audio_bps),
                    "-ac",
                    "1",
                    "-movflags",
                    "+faststart",
                    output_path,
                ]
                _run_ffmpeg(fallback_args)
            else:
                raise

    codecs_to_try = ["libx265", "libx264"] if prefer_h265 else ["libx264"]

    last_err = None
    selected_codec = None
    for codec in codecs_to_try:
        try:
            _encode(codec, video_bps)
            selected_codec = codec
            break
        except Exception as e:
            last_err = e
            try:
                if os.path.exists(output_path):
                    os.remove(output_path)
            except Exception:
                pass

    if not selected_codec:
        raise RuntimeError(str(last_err) if last_err else "Video encode failed.")

    # Iteratively reduce bitrate until we're under the target size.
    for _ in range(max_attempts - 1):
        try:
            size = os.path.getsize(output_path)
        except Exception:
            break

        if size <= target_bytes:
            return output_path

        # Reduce bitrate proportionally, with some headroom.
        ratio = target_bytes / max(size, 1)
        video_bps = max(120_000, int(video_bps * ratio * 0.92))

        try:
            os.remove(output_path)
        except Exception:
            pass

        _encode(selected_codec, video_bps)

    # Return best-effort even if slightly above target.
    return output_path

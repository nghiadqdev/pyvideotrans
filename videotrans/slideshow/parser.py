"""Parse script files (JSON or TXT) into a list of Scene objects."""

import json
import re
import os
from pathlib import Path
from typing import List, Optional, Tuple

from videotrans.slideshow import Scene


def parse_script(script_path: str, image_dir: str) -> List[Scene]:
    """Parse a script file and return a list of Scene objects.

    Supports two formats:
    1. JSON (extension .json or .slideshow)
    2. Plain text (extension .txt)
    """
    ext = Path(script_path).suffix.lower()

    if ext in (".json", ".slideshow"):
        return _parse_json(script_path, image_dir)
    elif ext == ".txt":
        return _parse_txt(script_path, image_dir)
    else:
        raise ValueError(f"Unsupported script format: {ext}. Use .json, .slideshow, or .txt")


def _resolve_image(image_name: str, image_dir: str) -> str:
    """Resolve an image path relative to image_dir."""
    if os.path.isabs(image_name) and os.path.exists(image_name):
        return image_name
    resolved = os.path.join(image_dir, image_name)
    if not os.path.exists(resolved):
        alt = os.path.join(image_dir, os.path.basename(image_name))
        if os.path.exists(alt):
            return alt
    return resolved


def _parse_timestamp(ts: str) -> int:
    """Parse a timestamp string like '00:00:05.500' or '00:00:05' to milliseconds."""
    ts = ts.strip()
    parts = re.split(r"[:.]", ts)
    if len(parts) == 3:
        h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
        return int(h * 3600000 + m * 60000 + s * 1000)
    elif len(parts) == 4:
        h, m, s, ms = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3].ljust(3, "0")[:3])
        return h * 3600000 + m * 60000 + s * 1000 + ms
    return 0


def _parse_txt(script_path: str, image_dir: str) -> List[Scene]:
    """Parse a TXT script file.

    Format:
        [00:00:00 --> 00:00:05] image1.jpg
        Narration text for the first image

        [00:00:05 --> 00:00:12] image2.jpg
        Narration text for the second image
    """
    with open(script_path, "r", encoding="utf-8") as f:
        content = f.read()

    scenes: List[Scene] = []
    # Match timestamp blocks with image
    pattern = re.compile(
        r"\[(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\s*-->\s*(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\]\s*(\S+)\s*\n\s*(.*?)(?=\n\s*\[|\Z)",
        re.DOTALL,
    )

    for match in pattern.finditer(content):
        start_ts = _parse_timestamp(match.group(1))
        end_ts = _parse_timestamp(match.group(2))
        image_name = match.group(3).strip()
        text = match.group(4).strip()

        image_path = _resolve_image(image_name, image_dir)

        scenes.append(Scene(
            start_ms=start_ts,
            end_ms=end_ts,
            image=image_path,
            text=text,
            transition="fade",
            effect="zoom_in",
        ))

    return scenes


def _parse_json(script_path: str, image_dir: str) -> List[Scene]:
    """Parse a JSON script file."""
    with open(script_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    scenes_data = data.get("scenes", [])
    if not scenes_data:
        raise ValueError("JSON script must contain a 'scenes' array")

    default_transition = data.get("default_transition", "fade")
    default_effect = data.get("default_effect", "zoom_in")

    scenes: List[Scene] = []
    for i, item in enumerate(scenes_data):
        start_ts = _parse_timestamp(str(item.get("start", "00:00:00")))
        end_ts = _parse_timestamp(str(item.get("end", "00:00:00")))
        image_name = item.get("image", "")
        text = item.get("text", "")
        transition = item.get("transition", default_transition)
        effect = item.get("effect", default_effect)

        image_path = _resolve_image(image_name, image_dir)

        if not text.strip():
            text = image_name  # fallback

        scenes.append(Scene(
            start_ms=start_ts,
            end_ms=end_ts,
            image=image_path,
            text=text,
            transition=transition,
            effect=effect,
        ))

    return scenes


def parse_script_meta(script_path: str) -> dict:
    """Parse script metadata (resolution, fps, bg_music, etc.) from JSON only."""
    ext = Path(script_path).suffix.lower()
    if ext not in (".json", ".slideshow"):
        return {}

    with open(script_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return {
        "resolution": data.get("resolution", ""),
        "fps": data.get("fps", 0),
        "bg_music": data.get("bg_music", ""),
        "bg_volume": data.get("bg_volume", 0.3),
        "default_transition": data.get("default_transition", "fade"),
        "transition_duration": data.get("transition_duration", 0.5),
        "default_effect": data.get("default_effect", "zoom_in"),
        "video_bitrate": data.get("video_bitrate", ""),
    }

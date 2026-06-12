"""Slideshow Video Creator - Script + Images -> Video

Supports:
- Script in JSON (.json/.slideshow) or TXT format
- TTS narration using existing TTS engines
- Image-to-video with Ken Burns effects
- Transition effects between scenes
- Background music overlay
- Subtitle overlay
"""

from dataclasses import dataclass, field
from typing import List, Optional

# Supported transitions mapped to FFmpeg xfade names
TRANSITIONS = {
    "fade": "fade",
    "fadeblack": "fadeblack",
    "fadewhite": "fadewhite",
    "dissolve": "dissolve",
    "wipeleft": "wipeleft",
    "wiperight": "wiperight",
    "wipeup": "wipeup",
    "wipedown": "wipedown",
    "slideleft": "slideleft",
    "slideright": "slideright",
    "slideup": "slideup",
    "slidedown": "slidedown",
    "circlecrop": "circlecrop",
    "pixelize": "pixelize",
    "hlslice": "hlslice",
    "hrslice": "hrslice",
    "vu_slice": "vuslice",
    "vd_slice": "vdslice",
}

# Ken Burns effects mapped to zoompan expressions
IMAGE_EFFECTS = {
    "none": None,
    "zoom_in": "zoompan=z='min(zoom+0.0015,1.2)':d={duration}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}",
    "zoom_out": "zoompan=z='max(zoom-0.0015,0.8)':d={duration}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}",
    "pan_left": "zoompan=z=1.1:d={duration}:x='min(iw/zoom*(1-1/1.1)+t*{pan_speed},iw-iw/zoom)':y='ih/2-(ih/zoom/2)':s={width}x{height}",
    "pan_right": "zoompan=z=1.1:d={duration}:x='max(iw/zoom*(0)-t*{pan_speed},0)':y='ih/2-(ih/zoom/2)':s={width}x{height}",
    "pan_up": "zoompan=z=1.1:d={duration}:x='iw/2-(iw/zoom/2)':y='min(ih/zoom*(1-1/1.1)+t*{pan_speed},ih-ih/zoom)':s={width}x{height}",
    "pan_down": "zoompan=z=1.1:d={duration}:x='iw/2-(iw/zoom/2)':y='max(ih/zoom*(0)-t*{pan_speed},0)':s={width}x{height}",
}

TRANSITION_NAMES = list(TRANSITIONS.keys())
EFFECT_NAMES = list(IMAGE_EFFECTS.keys())


@dataclass
class Scene:
    """A single scene in the slideshow."""
    start_ms: int
    end_ms: int
    image: str
    text: str
    transition: str = "fade"
    effect: str = "zoom_in"

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def duration_sec(self) -> float:
        return self.duration_ms / 1000.0


@dataclass
class SlideshowConfig:
    """Configuration for slideshow video creation."""
    script_file: str = ""
    image_dir: str = ""
    output_file: str = ""
    output_dir: str = ""
    resolution: str = "1920x1080"
    fps: int = 30
    video_bitrate: str = "4000k"
    tts_type: int = 0
    voice_role: str = "No"
    language: str = ""
    voice_rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"
    bg_music: str = ""
    bg_volume: float = 0.3
    default_transition: str = "fade"
    transition_duration: float = 0.5
    default_effect: str = "zoom_in"
    show_subtitle: bool = False
    scenes: List[Scene] = field(default_factory=list)
    uuid: str = ""
    is_cuda: bool = False

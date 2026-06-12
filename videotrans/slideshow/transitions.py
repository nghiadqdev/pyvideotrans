"""FFmpeg xfade transition definitions and helpers."""

from videotrans.slideshow import TRANSITIONS, IMAGE_EFFECTS


def get_xfade_name(transition: str) -> str:
    """Get the FFmpeg xfade transition name."""
    return TRANSITIONS.get(transition, "fade")


def get_effect_filter(effect: str, duration: float, width: int, height: int) -> str:
    """Get the FFmpeg filter string for an image effect (Ken Burns)."""
    if effect == "none" or effect not in IMAGE_EFFECTS:
        return ""

    template = IMAGE_EFFECTS[effect]
    if template is None:
        return ""

    pan_speed = max(width, height) * 0.05
    total_frames = int(duration * 30)

    return template.format(
        duration=total_frames,
        width=width,
        height=height,
        pan_speed=pan_speed,
    )

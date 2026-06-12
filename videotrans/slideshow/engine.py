"""Slideshow Engine - Main processing pipeline.

Takes a SlideshowConfig, generates TTS audio for each scene,
creates video clips from images, applies transitions, and outputs the final video.
"""

import os
import re
import subprocess
import tempfile
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from videotrans.slideshow import Scene, SlideshowConfig, TRANSITIONS, IMAGE_EFFECTS
from videotrans.slideshow.transitions import get_xfade_name, get_effect_filter
from videotrans.util.help_ffmpeg import runffmpeg
from videotrans.configure.config import logger


class SlideshowEngine:
    """Orchestrates the creation of a slideshow video from script + images."""

    def __init__(self, cfg: SlideshowConfig, progress_callback: Optional[Callable] = None):
        self.cfg = cfg
        self.progress_callback = progress_callback
        self.temp_dir = tempfile.mkdtemp(prefix="slideshow_")
        self.clip_files = []

    def _report(self, msg: str, percent: float = 0):
        """Report progress."""
        logger.info(f"[Slideshow] {msg}")
        if self.progress_callback:
            self.progress_callback(msg, percent)

    def _parse_resolution(self) -> tuple:
        """Parse resolution string like '1920x1080' to (width, height)."""
        parts = self.cfg.resolution.split("x")
        return int(parts[0]), int(parts[1])

    def run(self) -> str:
        """Run the complete pipeline. Returns the output video path."""
        try:
            self._report("Parsing script...", 0)
            if not self.cfg.scenes:
                raise RuntimeError("No scenes to process")

            width, height = self._parse_resolution()

            self._report("Generating TTS audio...", 5)
            self._generate_tts()

            self._report("Creating video clips from images...", 20)
            self._create_image_clips(width, height)

            self._report("Assembling final video...", 60)
            output = self._assemble_video(width, height)

            self._report("Done!", 100)
            return output
        finally:
            pass

    def cleanup(self):
        """Remove temp files."""
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    def _generate_tts(self):
        """Generate TTS audio for all scenes using the existing TTS module."""
        from videotrans.tts import run as run_tts

        queue_tts = []
        # Parse voice rate
        try:
            rate_str = str(self.cfg.voice_rate).replace("%", "").replace("+", "")
            rate_val = int(rate_str) if rate_str.lstrip("-").isdigit() else 0
        except (ValueError, TypeError):
            rate_val = 0
        rate = f"+{rate_val}%" if rate_val >= 0 else f"{rate_val}%"

        for i, scene in enumerate(self.cfg.scenes):
            txt = scene.text.strip()
            if not txt:
                txt = " "
            filename = os.path.join(self.temp_dir, f"tts_{i:04d}.wav")
            queue_tts.append({
                "text": txt,
                "line": i + 1,
                "start_time": scene.start_ms,
                "end_time": scene.end_ms,
                "startraw": scene.start_ms,
                "endraw": scene.end_ms,
                "ref_text": "",
                "start_time_source": scene.start_ms,
                "end_time_source": scene.end_ms,
                "role": self.cfg.voice_role,
                "rate": rate,
                "volume": self.cfg.volume,
                "pitch": self.cfg.pitch,
                "tts_type": self.cfg.tts_type,
                "filename": filename,
            })

        if not queue_tts:
            raise RuntimeError("No text to synthesize")

        self._report(f"Generating TTS for {len(queue_tts)} scenes...", 10)
        run_tts(
            queue_tts=queue_tts,
            language=self.cfg.language,
            uuid=self.cfg.uuid,
            tts_type=self.cfg.tts_type,
            is_cuda=self.cfg.is_cuda,
        )

        self._tts_files = [q["filename"] for q in queue_tts]
        self._report("TTS generation complete", 20)

    def _create_image_clips(self, width: int, height: int):
        """Create video clips from images for each scene, then merge with TTS audio."""
        total = len(self.cfg.scenes)

        def _process_one(idx: int) -> Optional[str]:
            scene = self.cfg.scenes[idx]
            tts_file = self._tts_files[idx]
            clip_file = os.path.join(self.temp_dir, f"clip_{idx:04d}.mp4")

            if self._create_clip(scene, tts_file, clip_file, width, height, idx + 1):
                return clip_file
            return None

        clip_files = [None] * total
        workers = min(total, max(4, os.cpu_count() or 4))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_process_one, i): i for i in range(total)}
            for future in as_completed(futures):
                i = futures[future]
                try:
                    result = future.result()
                    if result:
                        clip_files[i] = result
                    self._report(f"Scene {i+1}/{total} done", 20 + int(40 * (i + 1) / total))
                except Exception as e:
                    logger.error(f"[Slideshow] Error processing scene {i+1}: {e}")

        self.clip_files = [f for f in clip_files if f is not None]
        if len(self.clip_files) != total:
            raise RuntimeError(f"Only {len(self.clip_files)}/{total} clips generated successfully")

    def _create_clip(self, scene: Scene, tts_file: str, output: str, width: int, height: int, index: int) -> bool:
        """Create a single video clip: image + Ken Burns effect, then merge with TTS audio."""
        image = scene.image
        if not os.path.exists(image):
            logger.error(f"[Slideshow] Image not found: {image}")
            return False

        if not os.path.exists(tts_file):
            logger.error(f"[Slideshow] TTS audio not found: {tts_file}")
            return False

        duration = scene.duration_sec
        if duration <= 0:
            logger.error(f"[Slideshow] Invalid duration for scene {index}: {duration}s")
            return False

        total_frames = int(duration * self.cfg.fps)
        if total_frames < 1:
            total_frames = 1

        # Build video filter for image -> video with scaling + Ken Burns effect
        vf_parts = []
        vf_parts.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease")
        vf_parts.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")

        effect_filter = get_effect_filter(scene.effect, duration, width, height)
        if effect_filter:
            vf_parts.append(effect_filter)

        vf_parts.append(f"fps={self.cfg.fps}")
        vf_parts.append(f"format=yuv420p")

        vf_string = ",".join(vf_parts)

        # Create video from image
        temp_video = os.path.join(self.temp_dir, f"temp_video_{index:04d}.mp4")

        cmd = [
            "-loop", "1",
            "-i", image,
            "-vf", vf_string,
            "-t", str(duration),
            "-an",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            temp_video,
        ]

        try:
            self._run_ffmpeg(cmd, f"Image->Video scene {index}")
        except Exception as e:
            logger.error(f"[Slideshow] FFmpeg error creating video for scene {index}: {e}")
            return False

        if not os.path.exists(temp_video):
            return False

        # Check if TTS audio is longer than scene duration - need to trim
        import subprocess as sp
        audio_dur = self._get_audio_duration(tts_file)
        if audio_dur and audio_dur > duration + 0.5:
            trimmed_audio = os.path.join(self.temp_dir, f"tts_trimmed_{index:04d}.wav")
            trim_cmd = ["-i", tts_file, "-t", str(duration), "-c:a", "pcm_s16le", trimmed_audio]
            self._run_ffmpeg(trim_cmd, f"Trim audio {index}")
            tts_file = trimmed_audio

        # Merge video + audio
        merge_cmd = [
            "-i", temp_video,
            "-i", tts_file,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest",
            output,
        ]

        try:
            self._run_ffmpeg(merge_cmd, f"Merge scene {index}")
        except Exception as e:
            logger.error(f"[Slideshow] FFmpeg merge error for scene {index}: {e}")
            return False

        return os.path.exists(output)

    def _assemble_video(self, width: int, height: int) -> str:
        """Concatenate all clips with transitions using xfade filter, add background music, and output final video."""
        if len(self.clip_files) == 1:
            output = self.cfg.output_file
            if self.cfg.bg_music and os.path.exists(self.cfg.bg_music):
                self._add_bg_music(self.clip_files[0], self.cfg.bg_music, output)
            else:
                shutil.copy2(self.clip_files[0], output)
            return output

        # Build xfade filter complex
        filter_parts = []
        inputs = []
        prev_label = "0:v"
        prev_audio_label = "0:a"
        total_duration = 0.0
        fade_dur = self.cfg.transition_duration

        for i, clip in enumerate(self.clip_files):
            inputs.extend(["-i", clip])
            if i == 0:
                total_duration += self.cfg.scenes[i].duration_sec - fade_dur / 2
            elif i == len(self.clip_files) - 1:
                total_duration += self.cfg.scenes[i].duration_sec - fade_dur / 2
            else:
                total_duration += self.cfg.scenes[i].duration_sec - fade_dur

        for i in range(1, len(self.clip_files)):
            transition = self.cfg.scenes[i].transition if i < len(self.cfg.scenes) else "fade"
            xfade_name = get_xfade_name(transition)
            offset = sum(s.duration_sec for s in self.cfg.scenes[:i]) - fade_dur * i

            vid_out = f"v{i}"
            filter_parts.append(
                f"[{prev_label}][{i}:v]xfade=transition={xfade_name}:duration={fade_dur}:offset={offset}[{vid_out}]"
            )
            prev_label = vid_out

        # Audio crossfade
        for i in range(1, len(self.clip_files)):
            offset_a = sum(s.duration_sec for s in self.cfg.scenes[:i]) - fade_dur * i
            a_out = f"a{i}"
            filter_parts.append(
                f"[{prev_audio_label}][{i}:a]acrossfade=d={fade_dur}:c1=tri:c2=tri[{a_out}]"
            )
            prev_audio_label = a_out

        filter_complex = ";".join(filter_parts)

        output = self.cfg.output_file
        temp_no_bgm = os.path.join(self.temp_dir, "assembled_no_bgm.mp4")

        cmd = inputs + [
            "-filter_complex", filter_complex,
            "-map", f"[{prev_label}]",
            "-map", f"[{prev_audio_label}]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            temp_no_bgm,
        ]

        try:
            self._run_ffmpeg(cmd, "Assemble with transitions")
        except Exception as e:
            raise RuntimeError(f"Failed to assemble video: {e}")

        if self.cfg.bg_music and os.path.exists(self.cfg.bg_music):
            self._add_bg_music(temp_no_bgm, self.cfg.bg_music, output)
        else:
            shutil.copy2(temp_no_bgm, output)

        return output

    def _add_bg_music(self, video_file: str, music_file: str, output: str):
        """Mix background music into the video, looping if needed."""
        video_dur = self._get_video_duration(video_file)
        music_dur = self._get_audio_duration(music_file)

        bg_vol = self.cfg.bg_volume

        if music_dur and video_dur:
            loop_count = max(1, int(video_dur / music_dur) + 1)
            if loop_count > 50:
                loop_count = 1

            temp_music = os.path.join(self.temp_dir, "bg_music_looped.wav")
            loop_cmd = [
                "-stream_loop", str(loop_count),
                "-i", music_file,
                "-t", str(video_dur),
                "-c:a", "pcm_s16le",
                temp_music,
            ]
            self._run_ffmpeg(loop_cmd, "Loop background music")
            music_file = temp_music

        cmd = [
            "-i", video_file,
            "-i", music_file,
            "-filter_complex",
            f"[1:a]volume={bg_vol}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output,
        ]

        self._run_ffmpeg(cmd, "Add background music")

    def _run_ffmpeg(self, args: list, description: str = ""):
        """Run an FFmpeg command using the project's runffmpeg wrapper."""
        logger.debug(f"[Slideshow] FFmpeg: {description}")
        runffmpeg(args, force_cpu=True)

    @staticmethod
    def _get_audio_duration(filepath: str) -> float:
        """Get audio duration in seconds using ffprobe."""
        try:
            import subprocess as sp
            result = sp.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    filepath,
                ],
                capture_output=True,
                text=True,
            )
            return float(result.stdout.strip())
        except Exception:
            return 0.0

    @staticmethod
    def _get_video_duration(filepath: str) -> float:
        """Get video duration in seconds using ffprobe."""
        try:
            import subprocess as sp
            result = sp.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    filepath,
                ],
                capture_output=True,
                text=True,
            )
            return float(result.stdout.strip())
        except Exception:
            return 0.0

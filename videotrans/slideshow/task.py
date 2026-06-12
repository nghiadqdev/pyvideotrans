"""Slideshow Worker - QThread for running slideshow generation in the background."""

import os
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from videotrans.slideshow import SlideshowConfig
from videotrans.slideshow.engine import SlideshowEngine
from videotrans.configure.config import logger, app_cfg


class SlideshowWorker(QThread):
    """QThread worker that runs the slideshow engine and emits progress signals."""

    uito = Signal(dict)

    def __init__(self, cfg: SlideshowConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.engine = None

    def _progress_callback(self, msg: str, percent: float):
        """Called by engine to report progress."""
        if app_cfg.exit_soft:
            self.engine.cleanup()
            return

        self.uito.emit({
            "type": "logs",
            "text": msg,
            "uuid": self.cfg.uuid,
        })

        if percent > 0:
            self.uito.emit({
                "type": "set_precent",
                "text": f"{msg}???{percent}%",
                "uuid": self.cfg.uuid,
            })

    def run(self):
        """Run the slideshow generation pipeline."""
        try:
            self.uito.emit({
                "type": "logs",
                "text": "Starting slideshow generation...",
                "uuid": self.cfg.uuid,
            })

            engine = SlideshowEngine(self.cfg, progress_callback=self._progress_callback)
            self.engine = engine

            output = engine.run()

            self.uito.emit({
                "type": "succeed",
                "text": f"Video created: {output}",
                "uuid": self.cfg.uuid,
            })

        except Exception as e:
            logger.error(f"[Slideshow] Error: {e}", exc_info=True)
            self.uito.emit({
                "type": "error",
                "text": str(e),
                "uuid": self.cfg.uuid,
            })
        finally:
            if self.engine:
                self.engine.cleanup()

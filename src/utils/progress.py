import sys
import time


class Progress:
    """Small dependency-free terminal progress bar with elapsed time and ETA."""

    def __init__(self, label, total, width=28, stream=None):
        self.label = label
        self.total = max(0, int(total))
        self.width = width
        self.stream = stream or sys.stdout
        self.started = time.perf_counter()
        self.last_percent = -1

    @staticmethod
    def _clock(seconds):
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def update(self, completed, force=False):
        completed = max(0, min(int(completed), self.total))
        percent = 100 if self.total == 0 else int(completed * 100 / self.total)
        if not force and percent == self.last_percent:
            return
        self.last_percent = percent
        elapsed = time.perf_counter() - self.started
        rate = completed / elapsed if elapsed > 0 else 0
        remaining = (self.total - completed) / rate if rate > 0 else 0
        filled = int(self.width * percent / 100)
        bar = "#" * filled + "-" * (self.width - filled)
        line = (f"\r[*] [{self.label}] [{bar}] {percent:3d}% "
                f"{completed:,}/{self.total:,} | elapsed {self._clock(elapsed)} "
                f"| ETA {self._clock(remaining)}")
        self.stream.write(line)
        self.stream.flush()
        if percent >= 100:
            self.stream.write("\n")
            self.stream.flush()

    def finish(self):
        if self.last_percent < 100:
            self.update(self.total, force=True)
        return time.perf_counter() - self.started


def format_duration(seconds):
    return Progress._clock(seconds)

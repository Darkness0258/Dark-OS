#!/usr/bin/env python3
"""System metric sampler — CPU, GPU, RAM, storage, network from /proc and /sys."""

import shutil
import time
from pathlib import Path


class SystemSampler:
    """Read live system metrics without external dependencies beyond the OS."""

    def __init__(self):
        self.last_cpu = None
        self.last_network = None
        self.last_time = None

    def cpu_percent(self):
        try:
            first_line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
            fields = first_line.split()
            values = [int(value) for value in fields[1:]]
        except (OSError, IndexError, ValueError):
            return None
        if len(values) < 7 or fields[0] != "cpu":
            return None
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        current = (idle, total)
        if self.last_cpu is None:
            self.last_cpu = current
            return 0.0
        idle_delta = idle - self.last_cpu[0]
        total_delta = total - self.last_cpu[1]
        self.last_cpu = current
        if total_delta <= 0:
            return 0.0
        return 100.0 * (1.0 - idle_delta / total_delta)

    @staticmethod
    def memory_percent():
        values = {}
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                key, value = line.split(":", 1)
                values[key] = int(value.strip().split()[0])
        except (OSError, ValueError, IndexError):
            return None
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        return 100.0 * (total - available) / total if total else None

    @staticmethod
    def storage_percent():
        try:
            usage = shutil.disk_usage("/")
        except OSError:
            return None
        return 100.0 * usage.used / usage.total if usage.total else None

    @staticmethod
    def gpu_percent():
        for path in Path("/sys/class/drm").glob("card*/device/gpu_busy_percent"):
            try:
                return float(path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
        return None

    def network_rates(self):
        received = 0
        transmitted = 0
        try:
            lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
            for line in lines:
                interface, values = line.split(":", 1)
                if interface.strip() == "lo":
                    continue
                fields = values.split()
                received += int(fields[0])
                transmitted += int(fields[8])
        except (OSError, ValueError, IndexError):
            return None, None

        now = time.monotonic()
        if self.last_network is None or self.last_time is None:
            self.last_network = (received, transmitted)
            self.last_time = now
            return 0.0, 0.0
        elapsed = max(now - self.last_time, 0.001)
        down = max(0, received - self.last_network[0]) / elapsed
        up = max(0, transmitted - self.last_network[1]) / elapsed
        self.last_network = (received, transmitted)
        self.last_time = now
        return down, up

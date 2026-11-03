"""Offline reference for the proposed VFD reset pulse; never accesses hardware.

Q0.2 is evaluated separately from the motor state priority. A fault may need a
reset pulse while FAULT remains asserted and READY is low. Neither signal proves
standstill or grants any motor start permission. Default configuration blocks
the reset output. This reference is not a deployed or validated PLC program.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ResetConfig:
    interface_verified: bool = False
    pulse_seconds: float | None = None
    pulse_width_validated: bool = False

    @property
    def valid(self) -> bool:
        width = self.pulse_seconds
        return (self.interface_verified and self.pulse_width_validated
                and isinstance(width, (int, float)) and not isinstance(width, bool)
                and isfinite(width) and width > 0)


@dataclass(frozen=True)
class ResetInputs:
    button: bool = False
    start_buttons_released: bool = False
    run_forward: bool = False
    run_reverse: bool = False
    stop_nc_healthy: bool = False
    safety_ok: bool = False
    # Observed for review only: these must not veto a fault reset by themselves.
    fault_active: bool = False
    ready: bool = False


class ResetPulse:
    """Single output, fresh-edge pulse with immediate inhibit cancellation.

    Call once per simulated scan with monotonic time in seconds. A held button
    is consumed even while inhibited, so restoring safety cannot retrigger it.
    No method generates run commands, arms starts or verifies standstill.
    """

    def __init__(self, config: ResetConfig | None = None):
        self.config = config or ResetConfig()
        # The first sample establishes the baseline; a held power-up button
        # is not evidence of a fresh user request.
        self._last_button: bool | None = None
        self._last_time: float | None = None
        self._started_at: float | None = None

    def step(self, now: float, inputs: ResetInputs) -> bool:
        if not isfinite(now) or (self._last_time is not None and now < self._last_time):
            self._started_at = None
            raise ValueError("A finite monotonic simulation time is required")
        self._last_time = now
        rising = inputs.button and self._last_button is False
        self._last_button = inputs.button
        allowed = (self.config.valid and inputs.start_buttons_released
                   and not inputs.run_forward and not inputs.run_reverse
                   and inputs.stop_nc_healthy and inputs.safety_ok)
        if not allowed:
            self._started_at = None
            return False
        if self._started_at is not None:
            if now - self._started_at >= self.config.pulse_seconds:
                self._started_at = None
            # An edge during an existing pulse never extends or restarts it.
            return self._started_at is not None
        if rising:
            self._started_at = now
            return True
        return False


if __name__ == "__main__":
    print("Offline reset reference only. Default reset output is inhibited; no hardware access.")

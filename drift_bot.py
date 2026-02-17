#!/usr/bin/env python3
"""Foolproof controller anti-drift bot for Xbox/PlayStation pads.

This tool calibrates neutral stick drift, builds per-controller profiles,
and applies compensation in real time.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import statistics
import string
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

try:
    import pygame
except ImportError as exc:  # pragma: no cover - runtime dependency
    raise SystemExit(
        "Missing dependency: pygame. Install with `pip install -r requirements.txt`."
    ) from exc


PROFILE_DIR = pathlib.Path("profiles")
LEGACY_DEFAULT_PROFILE_PATH = PROFILE_DIR / "controller_profile.json"


@dataclass
class AxisCalibration:
    axis: int
    center: float
    deadzone: float

    def to_dict(self) -> Dict[str, float | int]:
        return {
            "axis": int(self.axis),
            "center": round(float(self.center), 6),
            "deadzone": round(float(self.deadzone), 6),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, float | int]) -> "AxisCalibration":
        return cls(
            axis=int(data["axis"]),
            center=float(data["center"]),
            deadzone=float(data["deadzone"]),
        )


@dataclass
class StickCalibration:
    x: AxisCalibration
    y: AxisCalibration

    def to_dict(self) -> Dict[str, Dict[str, float | int]]:
        return {"x": self.x.to_dict(), "y": self.y.to_dict()}

    @classmethod
    def from_dict(cls, data: Dict[str, Dict[str, float | int]]) -> "StickCalibration":
        return cls(
            x=AxisCalibration.from_dict(data["x"]),
            y=AxisCalibration.from_dict(data["y"]),
        )


@dataclass
class ControllerProfile:
    controller_name: str
    controller_guid: str
    generated_at: str
    axis_count: int
    left: StickCalibration
    right: StickCalibration

    def to_dict(self) -> Dict[str, object]:
        return {
            "controller_name": self.controller_name,
            "controller_guid": self.controller_guid,
            "generated_at": self.generated_at,
            "axis_count": self.axis_count,
            "sticks": {
                "left": self.left.to_dict(),
                "right": self.right.to_dict(),
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "ControllerProfile":
        sticks = data.get("sticks")
        if not isinstance(sticks, dict):
            raise ValueError("Invalid profile format: 'sticks' missing or malformed.")

        return cls(
            controller_name=str(data.get("controller_name", "Unknown Controller")),
            controller_guid=str(data.get("controller_guid", "unknown")),
            generated_at=str(data.get("generated_at", "unknown")),
            axis_count=int(data.get("axis_count", 0)),
            left=StickCalibration.from_dict(sticks["left"]),
            right=StickCalibration.from_dict(sticks["right"]),
        )


@dataclass
class ControllerInfo:
    index: int
    name: str
    guid: str
    axis_count: int
    button_count: int
    hat_count: int


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * p
    low_index = math.floor(index)
    high_index = math.ceil(index)
    if low_index == high_index:
        return sorted_values[low_index]
    low = sorted_values[low_index]
    high = sorted_values[high_index]
    frac = index - low_index
    return low + (high - low) * frac


def slugify(value: str) -> str:
    allowed = string.ascii_lowercase + string.digits
    cleaned = [ch.lower() if ch.lower() in allowed else "-" for ch in value.strip()]
    text = "".join(cleaned)
    while "--" in text:
        text = text.replace("--", "-")
    return text.strip("-") or "controller"


def prompt_with_default(prompt: str, default: str) -> str:
    try:
        raw = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        return default
    return raw or default


def prompt_yes_no(prompt: str, default: bool = True) -> bool:
    default_token = "Y/n" if default else "y/N"
    try:
        raw = input(f"{prompt} ({default_token}): ").strip().lower()
    except EOFError:
        return default

    if not raw:
        return default
    if raw in {"y", "yes"}:
        return True
    if raw in {"n", "no"}:
        return False
    return default


def wait_for_enter(message: str) -> None:
    print(message)
    try:
        input("Press Enter when ready... ")
    except EOFError:
        pass


def countdown(seconds: int) -> None:
    if seconds <= 0:
        return
    for remaining in range(seconds, 0, -1):
        print(f"Starting in {remaining}...", end="\r", flush=True)
        time.sleep(1)
    print(" " * 32, end="\r")


def init_input_system() -> None:
    pygame.init()
    pygame.joystick.init()


def shutdown_input_system() -> None:
    pygame.joystick.quit()
    pygame.quit()


def get_joystick_guid(joystick: pygame.joystick.Joystick) -> str:
    if hasattr(joystick, "get_guid"):
        try:
            guid = joystick.get_guid()
        except pygame.error:
            guid = "unknown"
    else:
        guid = "unknown"
    return str(guid or "unknown")


def read_controller_info(index: int) -> ControllerInfo:
    joystick = pygame.joystick.Joystick(index)
    joystick.init()
    info = ControllerInfo(
        index=index,
        name=str(joystick.get_name()),
        guid=get_joystick_guid(joystick),
        axis_count=joystick.get_numaxes(),
        button_count=joystick.get_numbuttons(),
        hat_count=joystick.get_numhats(),
    )
    joystick.quit()
    return info


def list_controllers() -> List[ControllerInfo]:
    return [read_controller_info(index) for index in range(pygame.joystick.get_count())]


def wait_for_controller(wait_seconds: float) -> None:
    if pygame.joystick.get_count() > 0:
        return

    timeout = max(1.0, float(wait_seconds))
    deadline = time.monotonic() + timeout
    print(f"No controller detected. Waiting up to {int(timeout)} seconds...")

    while time.monotonic() < deadline:
        pygame.joystick.quit()
        pygame.joystick.init()
        if pygame.joystick.get_count() > 0:
            return
        remaining = max(0, int(deadline - time.monotonic()))
        print(f"Connect controller now... {remaining:02d}s", end="\r", flush=True)
        time.sleep(1)

    print(" " * 40, end="\r")


def choose_controller_index(
    preferred_index: int | None,
    wait_seconds: float,
    interactive: bool,
) -> int:
    wait_for_controller(wait_seconds)
    controllers = list_controllers()

    if not controllers:
        raise RuntimeError("No controller detected. Connect your controller and retry.")

    if preferred_index is not None:
        valid_indexes = {controller.index for controller in controllers}
        if preferred_index not in valid_indexes:
            raise RuntimeError(
                f"Controller index {preferred_index} is unavailable. "
                f"Connected indexes: {sorted(valid_indexes)}"
            )
        return preferred_index

    if len(controllers) == 1:
        only = controllers[0]
        print(f"Auto-selected controller #0: {only.name}")
        return only.index

    print("Detected multiple controllers:")
    for controller in controllers:
        print(
            f"[{controller.index}] {controller.name} | "
            f"axes={controller.axis_count}, buttons={controller.button_count}, hats={controller.hat_count}"
        )

    if not interactive:
        print("Non-interactive mode: defaulting to controller #0.")
        return 0

    for _ in range(3):
        choice = prompt_with_default("Select controller index", "0")
        try:
            index = int(choice)
        except ValueError:
            print("Enter a valid number.")
            continue
        if any(controller.index == index for controller in controllers):
            return index
        print("That index is not in the list.")

    print("Too many invalid attempts. Using controller #0.")
    return 0


def init_controller(index: int) -> tuple[pygame.joystick.Joystick, ControllerInfo]:
    joystick = pygame.joystick.Joystick(index)
    joystick.init()

    info = ControllerInfo(
        index=index,
        name=str(joystick.get_name()),
        guid=get_joystick_guid(joystick),
        axis_count=joystick.get_numaxes(),
        button_count=joystick.get_numbuttons(),
        hat_count=joystick.get_numhats(),
    )
    return joystick, info


def reconnect_controller(target: ControllerInfo, wait_seconds: float) -> pygame.joystick.Joystick:
    print("Controller disconnected. Waiting for reconnection...")
    deadline = time.monotonic() + max(1.0, wait_seconds)

    while time.monotonic() < deadline:
        pygame.joystick.quit()
        pygame.joystick.init()
        for info in list_controllers():
            guid_match = target.guid != "unknown" and info.guid == target.guid
            name_match = info.name == target.name
            if guid_match or name_match:
                joystick = pygame.joystick.Joystick(info.index)
                joystick.init()
                print(f"Reconnected: {info.name} (index {info.index})")
                return joystick
        remaining = max(0, int(deadline - time.monotonic()))
        print(f"Reconnect controller... {remaining:02d}s", end="\r", flush=True)
        time.sleep(1)

    raise RuntimeError("Controller did not reconnect in time.")


def profile_path_for_controller(info: ControllerInfo) -> pathlib.Path:
    slug_name = slugify(info.name)
    guid_suffix = slugify(info.guid)[:12] if info.guid != "unknown" else "unknown"
    return PROFILE_DIR / f"{slug_name}_{guid_suffix}.json"


def iter_profile_paths() -> List[pathlib.Path]:
    paths: List[pathlib.Path] = []
    if PROFILE_DIR.exists():
        paths.extend(sorted(PROFILE_DIR.glob("*.json")))
    if LEGACY_DEFAULT_PROFILE_PATH.exists() and LEGACY_DEFAULT_PROFILE_PATH not in paths:
        paths.append(LEGACY_DEFAULT_PROFILE_PATH)
    return paths


def save_profile(profile: ControllerProfile, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), indent=2) + "\n", encoding="utf-8")


def load_profile(path: pathlib.Path) -> ControllerProfile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Profile file is not a valid JSON object.")
    return ControllerProfile.from_dict(raw)


def find_matching_profile_path(info: ControllerInfo) -> pathlib.Path | None:
    for path in iter_profile_paths():
        try:
            profile = load_profile(path)
        except Exception:
            continue

        if profile.controller_guid != "unknown" and info.guid != "unknown":
            if profile.controller_guid == info.guid:
                return path
        elif profile.controller_name.casefold() == info.name.casefold():
            return path
    return None


def choose_profile_path(info: ControllerInfo, explicit_path: pathlib.Path | None) -> pathlib.Path:
    if explicit_path is not None:
        return explicit_path

    existing = find_matching_profile_path(info)
    if existing is not None:
        return existing

    return profile_path_for_controller(info)


def collect_axis_spans(joystick: pygame.joystick.Joystick, duration_seconds: float) -> List[float]:
    axis_count = joystick.get_numaxes()
    mins = [1.0] * axis_count
    maxs = [-1.0] * axis_count

    end_time = time.monotonic() + duration_seconds
    while time.monotonic() < end_time:
        pygame.event.pump()
        for axis in range(axis_count):
            value = float(joystick.get_axis(axis))
            mins[axis] = min(mins[axis], value)
            maxs[axis] = max(maxs[axis], value)
        time.sleep(1 / 250)

    return [maxs[index] - mins[index] for index in range(axis_count)]


def pick_top_axis(spans: Sequence[float], excluded: Iterable[int] = ()) -> Tuple[int, float]:
    excluded_set = set(excluded)
    candidates = [(idx, span) for idx, span in enumerate(spans) if idx not in excluded_set]
    candidates.sort(key=lambda pair: pair[1], reverse=True)

    if not candidates:
        raise RuntimeError("No available axis candidates.")

    return candidates[0][0], candidates[0][1]


def discover_stick_axes(
    joystick: pygame.joystick.Joystick,
    sample_seconds: float,
) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    axis_count = joystick.get_numaxes()
    if axis_count < 4:
        raise RuntimeError(
            f"Controller reports only {axis_count} axes; at least 4 are required."
        )

    print("\nAxis mapping wizard")
    print("-------------------")

    detected_axes: List[int] = []
    spans: List[float] = []

    steps = [
        "Move ONLY the LEFT stick in full circles repeatedly.",
        "Keep moving ONLY the LEFT stick in full circles repeatedly.",
        "Move ONLY the RIGHT stick in full circles repeatedly.",
        "Keep moving ONLY the RIGHT stick in full circles repeatedly.",
    ]

    for step in steps:
        wait_for_enter(step)
        sample_spans = collect_axis_spans(joystick, sample_seconds)
        axis, span = pick_top_axis(sample_spans, excluded=detected_axes)
        detected_axes.append(axis)
        spans.append(span)
        print(f"Detected axis {axis} (movement span {span:.3f})")

    left_axes = (detected_axes[0], detected_axes[1])
    right_axes = (detected_axes[2], detected_axes[3])

    if min(spans) < 0.18:
        print(
            "Axis detection confidence was low. Falling back to default mapping "
            "left=(0,1), right=(2,3)."
        )
        left_axes = (0, 1)
        right_axes = (2, 3)

    return left_axes, right_axes


def collect_axis_samples(
    joystick: pygame.joystick.Joystick,
    axes: Sequence[int],
    duration_seconds: float,
) -> Dict[int, List[float]]:
    samples: Dict[int, List[float]] = {axis: [] for axis in axes}
    end_time = time.monotonic() + duration_seconds

    while time.monotonic() < end_time:
        pygame.event.pump()
        for axis in axes:
            samples[axis].append(float(joystick.get_axis(axis)))
        time.sleep(1 / 250)

    return samples


def build_axis_calibration(values: Sequence[float], axis: int) -> AxisCalibration:
    center = statistics.fmean(values)
    deviations = [abs(value - center) for value in values]
    p95 = percentile(deviations, 0.95)

    # P95 neutral noise + margin yields a stable deadzone for drift.
    deadzone = clamp((p95 * 2.2) + 0.01, 0.03, 0.35)

    return AxisCalibration(axis=axis, center=center, deadzone=deadzone)


def axis_health(deadzone: float) -> str:
    if deadzone <= 0.08:
        return "good"
    if deadzone <= 0.15:
        return "ok"
    if deadzone <= 0.24:
        return "high"
    return "severe"


def profile_quality(profile: ControllerProfile) -> tuple[str, List[str]]:
    checks = [
        profile.left.x,
        profile.left.y,
        profile.right.x,
        profile.right.y,
    ]

    findings: List[str] = []
    max_deadzone = max(axis.deadzone for axis in checks)
    max_center = max(abs(axis.center) for axis in checks)

    if max_deadzone > 0.30:
        findings.append(
            "Very large drift/noise detected (>30% deadzone). You may have moved a stick during calibration."
        )
    if max_center > 0.35:
        findings.append(
            "Large center offset detected (>0.35). Stick may be held off-center or heavily worn."
        )

    if findings:
        return "bad", findings

    if max_deadzone > 0.20 or max_center > 0.20:
        findings.append("Calibration is usable but drift appears heavy. Consider recalibrating.")
        return "warn", findings

    return "good", []


def calibrate_profile(
    joystick: pygame.joystick.Joystick,
    controller_info: ControllerInfo,
    left_axes: Tuple[int, int],
    right_axes: Tuple[int, int],
    neutral_seconds: float,
    max_attempts: int,
    interactive: bool,
) -> ControllerProfile:
    attempts = max(1, max_attempts)

    best_profile: ControllerProfile | None = None

    for attempt in range(1, attempts + 1):
        print(f"\nCalibration pass {attempt}/{attempts}")
        countdown(2)
        print(
            "Keep both sticks untouched during neutral calibration "
            f"({neutral_seconds:.1f}s)..."
        )

        all_axes = [left_axes[0], left_axes[1], right_axes[0], right_axes[1]]
        samples = collect_axis_samples(joystick, all_axes, neutral_seconds)

        profile = ControllerProfile(
            controller_name=controller_info.name,
            controller_guid=controller_info.guid,
            generated_at=dt.datetime.now().astimezone().isoformat(),
            axis_count=joystick.get_numaxes(),
            left=StickCalibration(
                x=build_axis_calibration(samples[left_axes[0]], left_axes[0]),
                y=build_axis_calibration(samples[left_axes[1]], left_axes[1]),
            ),
            right=StickCalibration(
                x=build_axis_calibration(samples[right_axes[0]], right_axes[0]),
                y=build_axis_calibration(samples[right_axes[1]], right_axes[1]),
            ),
        )

        best_profile = profile
        quality, findings = profile_quality(profile)

        if quality == "good":
            return profile

        for finding in findings:
            print(f"Warning: {finding}")

        if quality == "bad" and attempt < attempts:
            print("Retrying calibration automatically for a cleaner sample...")
            continue

        if quality == "warn" and attempt < attempts and interactive:
            if prompt_yes_no("Retry calibration for better accuracy?", default=True):
                continue

        return profile

    if best_profile is None:
        raise RuntimeError("Calibration failed unexpectedly.")

    return best_profile


def compensate_axis(value: float, calibration: AxisCalibration) -> float:
    shifted = value - calibration.center
    magnitude = abs(shifted)

    if magnitude <= calibration.deadzone:
        return 0.0

    normalized = (magnitude - calibration.deadzone) / max(1e-6, 1.0 - calibration.deadzone)
    normalized = clamp(normalized, 0.0, 1.0)
    return math.copysign(normalized, shifted)


def read_stick(joystick: pygame.joystick.Joystick, stick: StickCalibration) -> Tuple[float, float]:
    return float(joystick.get_axis(stick.x.axis)), float(joystick.get_axis(stick.y.axis))


def apply_profile(
    joystick: pygame.joystick.Joystick,
    profile: ControllerProfile,
) -> Dict[str, Tuple[float, float]]:
    left_raw = read_stick(joystick, profile.left)
    right_raw = read_stick(joystick, profile.right)

    left_fixed = (
        compensate_axis(left_raw[0], profile.left.x),
        compensate_axis(left_raw[1], profile.left.y),
    )
    right_fixed = (
        compensate_axis(right_raw[0], profile.right.x),
        compensate_axis(right_raw[1], profile.right.y),
    )

    return {
        "left_raw": left_raw,
        "right_raw": right_raw,
        "left_fixed": left_fixed,
        "right_fixed": right_fixed,
    }


def write_steam_hint(profile: ControllerProfile, path: pathlib.Path) -> pathlib.Path:
    left_pct = round(max(profile.left.x.deadzone, profile.left.y.deadzone) * 100)
    right_pct = round(max(profile.right.x.deadzone, profile.right.y.deadzone) * 100)

    hint_path = path.with_name(path.stem + "_steam_deadzone_hint.txt")
    hint = (
        "Steam Input deadzone suggestion\n"
        "==============================\n"
        f"Controller: {profile.controller_name}\n"
        f"Generated: {profile.generated_at}\n\n"
        f"Left stick deadzone:  {left_pct}%\n"
        f"Right stick deadzone: {right_pct}%\n\n"
        "Apply in Steam:\n"
        "1. Steam -> Settings -> Controller -> Calibration & Advanced Settings\n"
        "2. Set Left/Right stick deadzone to the values above\n"
        "3. Test in game and adjust +/- 2% if needed\n"
    )
    hint_path.write_text(hint, encoding="utf-8")
    return hint_path


def print_profile_summary(profile: ControllerProfile) -> None:
    checks = [
        ("Left", "X", profile.left.x),
        ("Left", "Y", profile.left.y),
        ("Right", "X", profile.right.x),
        ("Right", "Y", profile.right.y),
    ]

    print("\nCalibration summary")
    print("-------------------")
    print(f"Controller: {profile.controller_name}")
    print(f"Generated:  {profile.generated_at}")

    for side, axis_name, axis in checks:
        print(
            f"{side:5s} {axis_name} axis {axis.axis:2d} "
            f"center {axis.center:+.4f} deadzone {axis.deadzone:.3f} "
            f"({axis_health(axis.deadzone)})"
        )

    quality, findings = profile_quality(profile)
    if quality == "good":
        print("Drift grade: stable")
    elif quality == "warn":
        print("Drift grade: heavy but compensated")
    else:
        print("Drift grade: severe")

    for finding in findings:
        print(f"Note: {finding}")

    if quality == "bad":
        print("Recommendation: if drift stays severe, hardware replacement may be needed.")


def parse_axis_pair(value: str) -> Tuple[int, int]:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("Axis pair must look like: 0,1")

    try:
        first, second = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Axis values must be integers.") from exc

    if first == second:
        raise argparse.ArgumentTypeError("Axis values must be different.")

    return first, second


def validate_axes(axis_pair: Tuple[int, int], axis_count: int, label: str) -> None:
    first, second = axis_pair
    if first < 0 or second < 0 or first >= axis_count or second >= axis_count:
        raise RuntimeError(
            f"{label} axes {axis_pair} out of range for controller with {axis_count} axes."
        )


def load_profile_or_raise(path: pathlib.Path) -> ControllerProfile:
    if not path.exists():
        raise RuntimeError(f"Profile not found at {path}.")
    try:
        return load_profile(path)
    except Exception as exc:
        raise RuntimeError(f"Profile is unreadable at {path}: {exc}") from exc


def profile_matches_controller(profile: ControllerProfile, info: ControllerInfo) -> bool:
    if profile.controller_guid != "unknown" and info.guid != "unknown":
        return profile.controller_guid == info.guid
    return profile.controller_name.casefold() == info.name.casefold()


def run_live_loop(
    joystick: pygame.joystick.Joystick,
    controller_info: ControllerInfo,
    profile: ControllerProfile,
    fps: int,
    duration_seconds: float | None,
    reconnect_wait_seconds: float,
) -> None:
    print("\nLive anti-drift output (Ctrl+C to stop):")
    print("raw -> fixed")

    frame_delay = 1 / max(20, fps)
    end_time = None if duration_seconds is None else time.monotonic() + duration_seconds

    while True:
        if end_time is not None and time.monotonic() >= end_time:
            print("\nLive run finished.")
            return

        try:
            pygame.event.pump()
            readings = apply_profile(joystick, profile)
        except pygame.error:
            joystick = reconnect_controller(controller_info, reconnect_wait_seconds)
            continue

        left_raw = readings["left_raw"]
        right_raw = readings["right_raw"]
        left_fixed = readings["left_fixed"]
        right_fixed = readings["right_fixed"]

        line = (
            f"L ({left_raw[0]:+0.3f},{left_raw[1]:+0.3f}) -> ({left_fixed[0]:+0.3f},{left_fixed[1]:+0.3f}) | "
            f"R ({right_raw[0]:+0.3f},{right_raw[1]:+0.3f}) -> ({right_fixed[0]:+0.3f},{right_fixed[1]:+0.3f})"
        )
        print(f"\r{line}", end="", flush=True)
        time.sleep(frame_delay)


def run_calibration(
    args: argparse.Namespace,
    joystick: pygame.joystick.Joystick,
    controller_info: ControllerInfo,
    profile_path: pathlib.Path,
    interactive: bool,
) -> ControllerProfile:
    axis_count = joystick.get_numaxes()

    if args.left_axes and args.right_axes:
        validate_axes(args.left_axes, axis_count, "Left")
        validate_axes(args.right_axes, axis_count, "Right")
        left_axes, right_axes = args.left_axes, args.right_axes
    else:
        left_axes, right_axes = discover_stick_axes(joystick, args.mapping_sample_seconds)

    print(f"Detected left stick axes:  {left_axes[0]}, {left_axes[1]}")
    print(f"Detected right stick axes: {right_axes[0]}, {right_axes[1]}")

    profile = calibrate_profile(
        joystick=joystick,
        controller_info=controller_info,
        left_axes=left_axes,
        right_axes=right_axes,
        neutral_seconds=args.neutral_sample_seconds,
        max_attempts=args.max_calibration_attempts,
        interactive=interactive,
    )

    save_profile(profile, profile_path)
    hint_path = write_steam_hint(profile, profile_path)

    print_profile_summary(profile)
    print(f"\nSaved profile: {profile_path}")
    print(f"Saved Steam deadzone hint: {hint_path}")

    return profile


def print_controller_list(wait_seconds: float) -> int:
    wait_for_controller(wait_seconds)
    controllers = list_controllers()

    if not controllers:
        print("No controllers detected.")
        return 1

    print("Connected controllers")
    print("---------------------")
    for controller in controllers:
        suggested_profile = profile_path_for_controller(controller)
        print(
            f"[{controller.index}] {controller.name} | guid={controller.guid} | "
            f"axes={controller.axis_count} buttons={controller.button_count} hats={controller.hat_count}"
        )
        print(f"    Suggested profile: {suggested_profile}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Foolproof stick-drift calibration and compensation tool."
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="quickfix",
        choices=["quickfix", "wizard", "calibrate", "run", "doctor", "list"],
        help=(
            "quickfix (default): auto-load or calibrate then run; "
            "wizard: always recalibrate then run; "
            "calibrate: save profile only; run: run from profile; "
            "doctor: inspect profile health; list: list controllers"
        ),
    )
    parser.add_argument(
        "--controller-index",
        type=int,
        default=None,
        help="Controller index. If omitted, tool auto-selects or prompts.",
    )
    parser.add_argument(
        "--profile",
        type=pathlib.Path,
        default=None,
        help="Explicit profile JSON path. Defaults to per-controller profile.",
    )
    parser.add_argument(
        "--mapping-sample-seconds",
        type=float,
        default=2.5,
        help="Seconds per axis-mapping step.",
    )
    parser.add_argument(
        "--neutral-sample-seconds",
        type=float,
        default=3.5,
        help="Seconds to sample neutral drift during calibration.",
    )
    parser.add_argument(
        "--max-calibration-attempts",
        type=int,
        default=3,
        help="Maximum calibration retries (default: 3).",
    )
    parser.add_argument(
        "--left-axes",
        type=parse_axis_pair,
        help="Override left stick axes, e.g. --left-axes 0,1",
    )
    parser.add_argument(
        "--right-axes",
        type=parse_axis_pair,
        help="Override right stick axes, e.g. --right-axes 2,3",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=60,
        help="Update rate for live mode (default: 60).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Optional run duration in seconds.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=30,
        help="How long to wait for controller connect/reconnect (default: 30).",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Avoid prompts and use safe defaults.",
    )
    parser.add_argument(
        "--force-recalibrate",
        action="store_true",
        help="Force recalibration even when a profile already exists.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    interactive = not args.non_interactive

    init_input_system()
    joystick: pygame.joystick.Joystick | None = None

    try:
        if args.command == "list":
            return print_controller_list(args.wait_seconds)

        controller_index = choose_controller_index(
            preferred_index=args.controller_index,
            wait_seconds=args.wait_seconds,
            interactive=interactive,
        )

        joystick, controller_info = init_controller(controller_index)
        print(f"Using controller #{controller_index}: {controller_info.name}")

        profile_path = choose_profile_path(controller_info, args.profile)

        if args.command == "calibrate":
            run_calibration(args, joystick, controller_info, profile_path, interactive)
            return 0

        if args.command == "wizard":
            profile = run_calibration(args, joystick, controller_info, profile_path, interactive)
            run_live_loop(
                joystick,
                controller_info,
                profile,
                fps=args.fps,
                duration_seconds=args.duration,
                reconnect_wait_seconds=args.wait_seconds,
            )
            return 0

        if args.command == "doctor":
            profile = load_profile_or_raise(profile_path)
            print_profile_summary(profile)
            print(f"\nProfile path: {profile_path}")
            return 0

        if args.command == "run":
            profile = load_profile_or_raise(profile_path)
            if not profile_matches_controller(profile, controller_info):
                print(
                    "Warning: profile was created for a different controller model/GUID. "
                    "Compensation may be less accurate."
                )
            run_live_loop(
                joystick,
                controller_info,
                profile,
                fps=args.fps,
                duration_seconds=args.duration,
                reconnect_wait_seconds=args.wait_seconds,
            )
            return 0

        # quickfix (default)
        use_existing = False
        if profile_path.exists() and not args.force_recalibrate:
            try:
                existing_profile = load_profile(profile_path)
                use_existing = True
            except Exception:
                print("Existing profile is unreadable; recalibrating.")
                use_existing = False

            if use_existing and interactive:
                same_controller = profile_matches_controller(existing_profile, controller_info)
                if not same_controller:
                    print("Existing profile is for another controller.")
                    use_existing = False
                else:
                    use_existing = prompt_yes_no(
                        f"Use existing profile at {profile_path}?",
                        default=True,
                    )

        if use_existing:
            profile = load_profile(profile_path)
            print(f"Loaded profile: {profile_path}")
        else:
            profile = run_calibration(args, joystick, controller_info, profile_path, interactive)

        run_live_loop(
            joystick,
            controller_info,
            profile,
            fps=args.fps,
            duration_seconds=args.duration,
            reconnect_wait_seconds=args.wait_seconds,
        )
        return 0

    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    finally:
        if joystick is not None:
            try:
                joystick.quit()
            except Exception:
                pass
        shutdown_input_system()


if __name__ == "__main__":
    raise SystemExit(main())

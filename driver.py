import subprocess
import time
import re
import shlex
import logging
import sys
import os
import json
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

# ─────────────────────────────────────────────────────────────────────────────
# Platform-specific subprocess flags
# CREATE_NO_WINDOW suppresses the console window on Windows; not available
# on other platforms, so it is applied conditionally.
# ─────────────────────────────────────────────────────────────────────────────
_SUBPROCESS_FLAGS = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if sys.platform == "win32"
    else {}
)

# ─────────────────────────────────────────────────────────────────────────────
# Config defaults (single source of truth — imported by app.py)
# ─────────────────────────────────────────────────────────────────────────────
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "adb_address":   "127.0.0.1:5575",
    "package_name":  "com.rovio.angrybirdstransformers",
    "activity_name": "com.rovio.angrybirdstransformers.AngryBirdsTransformersActivity",
    "btn_x": 720,
    "btn_y": 890,
}

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
LOG_FILE         = "farm_log.txt"
LOG_MAX_BYTES    = 5 * 1024 * 1024   # 5 MB per file
LOG_BACKUP_COUNT = 3                  # keep 3 old backups (~20 MB total)

COORD_MIN = 0
COORD_MAX = 9999

# ADB address validation: 'ip:port', e.g. '127.0.0.1:5575'
_ADB_ADDR_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}$")

# Android package / activity name validation:
# at least two dot-separated segments, each starting with a letter.
_ANDROID_NAME_RE = re.compile(
    r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$"
)

# stop_game() polling parameters
STOP_GAME_TIMEOUT = 10   # seconds before giving up and logging a warning
STOP_GAME_POLL    = 0.5  # interval between foreground checks

# Timeout for ADB subprocess calls.
# Prevents an indefinite hang when the emulator crashes or the port drops.
ADB_CMD_TIMEOUT     = 15   # seconds — run_cmd()
ADB_CONNECT_TIMEOUT = 10   # seconds — initial adb connect


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_adb_path() -> str:
    """
    Returns the correct path to adb.exe depending on the runtime context:
      - Plain .py script  -> looks next to this file
      - PyInstaller .exe  -> looks in the temp extraction folder (_MEIPASS)
    """
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "adb.exe")


def setup_rotating_log(log_file: str = LOG_FILE) -> None:
    """
    Attaches a RotatingFileHandler to the root logger.
    Rotates when the file reaches LOG_MAX_BYTES; keeps LOG_BACKUP_COUNT backups.
    Safe to call multiple times — checks for an existing handler with the
    same path and returns immediately if already configured.
    """
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, RotatingFileHandler) and \
                h.baseFilename == os.path.abspath(log_file):
            return  # already configured
    try:
        rh = RotatingFileHandler(
            log_file,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        rh.setFormatter(
            logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
        )
        root.addHandler(rh)
    except Exception as exc:
        logging.warning(f"[LOG] Failed to configure rotating log: {exc}")


def validate_adb_address(address: str) -> str:
    """
    Validates the ADB address against the 'ip:port' pattern.
    Raises ValueError on mismatch so misconfigured values are caught early,
    before any shell command is constructed.
    """
    if not _ADB_ADDR_RE.match(address.strip()):
        raise ValueError(
            f"Invalid ADB address format: '{address}'. "
            "Expected 'ip:port', e.g. '127.0.0.1:5575'."
        )
    return address.strip()


def validate_package_name(name: str) -> str:
    """
    Validates that the Android package name is well-formed
    (e.g. 'com.rovio.angrybirdstransformers').
    Raises ValueError on mismatch.
    """
    if not _ANDROID_NAME_RE.match(name.strip()):
        raise ValueError(
            f"Invalid package name: '{name}'. "
            "Expected format: 'com.company.app'."
        )
    return name.strip()


def validate_activity_name(name: str) -> str:
    """
    Validates that the Android activity name is well-formed
    (e.g. 'com.rovio.angrybirdstransformers.AngryBirdsTransformersActivity').
    Raises ValueError on mismatch.
    """
    if not _ANDROID_NAME_RE.match(name.strip()):
        raise ValueError(
            f"Invalid activity name: '{name}'. "
            "Expected format: 'com.company.app.ActivityName'."
        )
    return name.strip()


def validate_coords(x: int, y: int) -> tuple:
    """
    Validates that tap coordinates are within [COORD_MIN .. COORD_MAX].
    Raises ValueError if either coordinate is out of range.
    """
    if not (COORD_MIN <= x <= COORD_MAX and COORD_MIN <= y <= COORD_MAX):
        raise ValueError(
            f"Coordinates ({x}, {y}) are outside the valid range "
            f"[{COORD_MIN}..{COORD_MAX}]."
        )
    return x, y


def load_config_driver() -> dict:
    """
    Reads CONFIG_FILE and merges the result with DEFAULT_CONFIG so that any
    missing keys are filled in automatically.
    Returns a copy of DEFAULT_CONFIG on any read or parse error.
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except json.JSONDecodeError as e:
            logging.warning(f"[CONFIG] config.json is malformed, using defaults: {e}")
        except Exception as e:
            logging.warning(f"[CONFIG] Could not read config.json: {e}")
    return DEFAULT_CONFIG.copy()


# ─────────────────────────────────────────────────────────────────────────────
# GameDriver
# ─────────────────────────────────────────────────────────────────────────────

class GameDriver:

    def __init__(
        self,
        adb_address:   str = "127.0.0.1:5575",
        package_name:  str = "com.rovio.angrybirdstransformers",
        activity_name: str = "com.rovio.angrybirdstransformers.AngryBirdsTransformersActivity",
    ):
        # Validate all three identifiers at construction time so that a typo
        # in Settings is surfaced immediately, before any ADB command runs.
        self.adb_address   = validate_adb_address(adb_address)
        self.package_name  = validate_package_name(package_name)
        self.activity_name = validate_activity_name(activity_name)
        self._adb          = get_adb_path()
        # Check ADB files once at init; result is cached to avoid a repeated
        # disk syscall on every run_cmd() invocation.
        self._adb_ok       = self._check_adb()

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _check_adb(self) -> bool:
        """
        Verifies that all three required ADB files are present on disk.
        Called once in __init__; result is cached in self._adb_ok.
        """
        base     = os.path.dirname(self._adb)
        required = ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"]
        missing  = [f for f in required if not os.path.isfile(os.path.join(base, f))]
        if missing:
            logging.error(
                f"ADB files not found: {', '.join(missing)}. "
                "Please ensure all ADB files are in the same folder as the program."
            )
            return False
        return True

    def _build_cmd(self, command: str) -> list:
        """
        Builds the full ADB invocation as a list of arguments.

        Uses shlex.split() instead of str.split() so that quoted arguments
        such as  su -c 'date 042823592026.00'  are kept as a single token
        and not broken across multiple list elements.
        Passing a list with shell=False completely prevents shell injection.
        """
        return [self._adb, "-s", self.adb_address] + shlex.split(command)

    def run_cmd(self, command: str) -> str:
        """
        Executes an ADB command and returns stdout as a stripped string.
        Never raises — returns "" on any error to keep callers simple.

        Times out after ADB_CMD_TIMEOUT seconds so a crashed or unresponsive
        emulator does not block the farming thread indefinitely.
        """
        if not self._adb_ok:
            return ""
        try:
            result = subprocess.run(
                self._build_cmd(command),
                shell=False,
                capture_output=True,
                text=True,
                timeout=ADB_CMD_TIMEOUT,
                **_SUBPROCESS_FLAGS,
            )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logging.error(
                f"[ADB] Command timed out after {ADB_CMD_TIMEOUT}s: {command!r}. "
                "The emulator may be unresponsive."
            )
            return ""
        except FileNotFoundError:
            logging.error("[ADB] adb.exe not found. Check the program folder.")
            return ""
        except Exception as exc:
            logging.error(f"[ADB] Command execution error: {exc}")
            return ""

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """
        Establishes an ADB connection to the emulator.
        Disables Android's automatic time sync on success so the emulator
        does not fight the script during date manipulation.
        """
        if not self._adb_ok:
            return False
        logging.info(f"Connecting to {self.adb_address}...")
        try:
            subprocess.run(
                [self._adb, "connect", self.adb_address],
                shell=False,
                capture_output=True,
                timeout=ADB_CONNECT_TIMEOUT,
                **_SUBPROCESS_FLAGS,
            )
        except subprocess.TimeoutExpired:
            logging.error(
                f"[ADB] Connect timed out after {ADB_CONNECT_TIMEOUT}s. "
                "Check that BlueStacks is running and ADB is enabled."
            )
            return False
        except Exception as exc:
            logging.error(f"[ADB] Connect error: {exc}")
            return False

        state = self.run_cmd("get-state")
        if "device" in state:
            logging.info("Connection established successfully!")
            self.run_cmd("shell su -c 'settings put global auto_time 0'")
            return True
        else:
            logging.error("Emulator not found. Check ADB settings in BlueStacks.")
            return False

    def verify_package_installed(self) -> bool:
        """
        Checks whether the configured package is installed on the device.
        Queries 'pm list packages' and matches full 'package:<name>' lines
        to avoid false positives from packages whose name is a substring
        of another package name.
        """
        output = self.run_cmd("shell pm list packages")
        target = f"package:{self.package_name}"
        for line in output.splitlines():
            if line.strip() == target:
                return True
        return False

    def verify_activity_exists(self) -> bool:
        """
        Checks that the configured activity class is registered in the package
        manifest by inspecting 'dumpsys package' output.

        Uses the short-form token '<package>/.<ShortClassName>' for matching
        because 'am resolve-activity' always returns 'Activity:' on BlueStacks
        regardless of whether the class actually exists.

        Returns False immediately if activity_name does not start with
        package_name + '.', catching prefix typos without any ADB call.
        """
        expected_prefix = self.package_name + "."
        if not self.activity_name.startswith(expected_prefix):
            logging.warning(
                f"[VERIFY] Activity '{self.activity_name}' does not start with "
                f"package name '{self.package_name}.'"
            )
            return False

        pkg_dump    = self.run_cmd(f"shell dumpsys package {self.package_name}")
        short_class = self.activity_name.rsplit(".", 1)[-1]
        full_token  = f"{self.package_name}/.{short_class}"

        if full_token in pkg_dump:
            return True

        logging.warning(
            f"[VERIFY] Activity '{self.activity_name}' not found. "
            f"Looked for '{full_token}' in dumpsys package output."
        )
        return False

    def get_device_time(self) -> datetime:
        """
        Fetches the current time from the emulator via 'date +%m%d%H%M%Y.%S'.
        Raises RuntimeError on parse failure — the caller handles this
        explicitly and aborts the farming loop instead of silently using
        the host PC time as a fallback.
        """
        raw_res   = self.run_cmd("shell su -c 'date +%m%d%H%M%Y.%S'")
        clean_res = re.sub(r'[^0-9.]', '', raw_res)
        try:
            return datetime.strptime(clean_res, "%m%d%H%M%Y.%S")
        except Exception:
            raise RuntimeError(
                f"Failed to read device time (raw response: '{raw_res}'). "
                "Please verify root access and the emulator connection."
            )

    def set_device_time(self, dt_obj: datetime):
        """Sets the system time inside the rooted emulator."""
        adb_date = dt_obj.strftime("%m%d%H%M%Y.%S")
        self.run_cmd(f"shell su -c 'date {adb_date}'")
        logging.info(f"[TIME] Device time set to: {dt_obj.strftime('%d.%m.%Y %H:%M')}")

    def click(self, x: int, y: int):
        """
        Emulates a screen tap at the specified coordinates.
        Coordinates are validated via validate_coords() before the tap is sent;
        ValueError is raised and propagated if they are out of range.
        """
        validate_coords(x, y)
        self.run_cmd(f"shell input tap {x} {y}")
        logging.info(f"[ACTION] Tapped coordinates: X={x}, Y={y}")

    def skip_days(self, days_to_skip: int):
        """
        Jumps forward a specified number of days from the emulator's current time.
        RuntimeError from get_device_time() propagates to the caller, aborting
        the farming loop cleanly instead of silently using the wrong timestamp.
        """
        current_time = self.get_device_time()   # may raise RuntimeError
        new_time     = current_time + timedelta(days=days_to_skip)
        self.set_device_time(new_time)
        logging.info(f"[ACTION] Skipped forward {days_to_skip} day(s).")

    def apply_fix(self):
        """Reverts the emulator clock to yesterday at 23:59:00 to trigger
        the calendar fix — one minute before a natural midnight rollover."""
        real_yesterday = (datetime.now() - timedelta(days=1)).replace(
            hour=23, minute=59, second=0, microsecond=0)
        logging.info("[FIX] Reverting time to yesterday 23:59...")
        self.set_device_time(real_yesterday)

    def is_game_foreground(self) -> bool:
        """
        Returns True if the game's Activity is currently in the foreground.

        Checks all lines containing 'mResumedActivity' or 'ResumedActivity'
        (not just the first) to avoid race-condition false negatives.
        Falls back to a 'mCurrentFocus' window check as a secondary signal.
        Both fetches avoid shell pipes so shell=False remains safe.
        """
        activity_output = self.run_cmd("shell dumpsys activity activities")
        for line in activity_output.splitlines():
            if ("mResumedActivity" in line or "ResumedActivity" in line) \
                    and self.package_name in line:
                return True

        window_output = self.run_cmd("shell dumpsys window windows")
        for line in window_output.splitlines():
            if "mCurrentFocus" in line and self.package_name in line:
                return True

        return False

    def stop_game(self):
        """
        Force-stops the game and polls until it disappears from the foreground
        or STOP_GAME_TIMEOUT seconds have elapsed.
        Logs a warning if the timeout is reached without confirmation.
        """
        self.run_cmd(f"shell am force-stop {self.package_name}")
        logging.info("[ACTION] Stop command sent, waiting for confirmation...")

        deadline = time.time() + STOP_GAME_TIMEOUT
        while time.time() < deadline:
            time.sleep(STOP_GAME_POLL)
            if not self.is_game_foreground():
                logging.info("[ACTION] Game stopped successfully.")
                return

        logging.warning(
            f"[ACTION] Game did not stop within {STOP_GAME_TIMEOUT}s. "
            "Continuing — results may be unstable."
        )

    def start_game(self) -> bool:
        """
        Launches the game using its specific Activity path.
        Returns True if the game is confirmed in the foreground after launch.
        Returns False on an am-start error or if the foreground check fails,
        so the caller can react to a failed launch instead of silently continuing.
        """
        logging.info(f"[ACTION] Launching {self.package_name}...")
        self.run_cmd("shell input keyevent 3")
        time.sleep(1)

        output = self.run_cmd(
            f"shell am start -S -W -n {self.package_name}/{self.activity_name}"
        )

        if "Error:" in output or "does not exist" in output:
            logging.error(f"[ERROR] am start failed: {output}")
            return False

        time.sleep(7)
        if self.is_game_foreground():
            logging.info("[SUCCESS] Game launched successfully.")
            return True

        logging.warning(
            "[WARNING] Game not detected in foreground after launch. "
            "Please check the emulator screen."
        )
        return False
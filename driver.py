import subprocess
import time
import re
import logging
import sys
import os
import subprocess
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

LOG_FILE         = "farm_log.txt"
LOG_MAX_BYTES    = 5 * 1024 * 1024  # 5 MB per file
LOG_BACKUP_COUNT = 3                 # keep 3 old backups (~20 MB total)

# Valid coordinate range for tap commands (fix #9)
COORD_MIN = 0
COORD_MAX = 9999

# ADB address validation pattern (fix #2)
_ADB_ADDR_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}$")

# Timeout constants for stop_game polling (fix #6)
STOP_GAME_TIMEOUT = 10   # seconds
STOP_GAME_POLL    = 0.5  # polling interval


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_adb_path() -> str:
    """
    Returns the correct path to adb.exe whether running:
      - As a plain .py script  -> looks next to this file
      - As a PyInstaller .exe  -> looks in the temp extraction folder (_MEIPASS)
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
    Safe to call multiple times — duplicate handlers are not added.

    FIX #8: replaces unbounded farm_log.txt growth with a rotating handler
    (5 MB x 3 backups = ~20 MB max). Rotation happens at write time when the
    current file exceeds the size limit.
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
    Validates that the ADB address matches the expected 'ip:port' format.

    FIX #2: without this check, an arbitrary string from config.json was
    interpolated directly into a shell command, enabling Command Injection.

    Raises:
        ValueError: if the format is invalid.
    """
    if not _ADB_ADDR_RE.match(address.strip()):
        raise ValueError(
            f"Invalid ADB address format: '{address}'. "
            "Expected 'ip:port', e.g. '127.0.0.1:5575'."
        )
    return address.strip()


def validate_coords(x: int, y: int) -> tuple:
    """
    Validates that tap coordinates are within the accepted range.

    FIX #9: negative or excessively large coordinates coming from config.json
    could cause unpredictable behaviour in the tap command.

    Raises:
        ValueError: if either coordinate is out of range.
    """
    if not (COORD_MIN <= x <= COORD_MAX and COORD_MIN <= y <= COORD_MAX):
        raise ValueError(
            f"Coordinates ({x}, {y}) are outside the valid range "
            f"[{COORD_MIN}..{COORD_MAX}]."
        )
    return x, y


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
        # FIX #2: validate the address at construction time so the error
        # surfaces early, before any command is executed.
        self.adb_address   = validate_adb_address(adb_address)
        self.package_name  = package_name
        self.activity_name = activity_name
        self._adb          = get_adb_path()

        # FIX #7: check ADB files once at init and cache the result instead
        # of repeating the filesystem check on every run_cmd call.
        self._adb_ok = self._check_adb()

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _check_adb(self) -> bool:
        """
        Verifies that all three required ADB files are present.
        Called once in __init__; result is cached in self._adb_ok.

        FIX #7: eliminates repeated disk syscalls on every run_cmd invocation.
        """
        base = os.path.dirname(self._adb)
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
        Builds the ADB command as a list of arguments (no shell interpolation).

        FIX #1 (Command Injection): the original code used shell=True with an
        f-string that embedded adb_address directly — a malicious config.json
        could inject arbitrary shell commands. Passing arguments as a list
        completely prevents shell interpretation.
        """
        return [self._adb, "-s", self.adb_address] + command.split()

    def run_cmd(self, command: str) -> str:
        """
        Executes an ADB command and returns stdout.

        FIX #1: shell=True replaced with argument list.
        FIX #7: ADB file check removed from here; cached self._adb_ok is used.
        """
        if not self._adb_ok:
            return ""
        try:
            result = subprocess.run(
                self._build_cmd(command),
                shell=False,        # <- key fix #1
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return result.stdout.strip()
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
        """Establishes connection with the BlueStacks emulator."""
        if not self._adb_ok:
            return False
        logging.info(f"Connecting to {self.adb_address}...")
        try:
            subprocess.run(
                [self._adb, "connect", self.adb_address],
                shell=False,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as exc:
            logging.error(f"[ADB] Connect error: {exc}")
            return False

        state = self.run_cmd("get-state")
        if "device" in state:
            logging.info("Connection established successfully!")
            # Disable automatic time synchronization
            self.run_cmd("shell su -c 'settings put global auto_time 0'")
            return True
        else:
            logging.error("Emulator not found. Check ADB settings in BlueStacks.")
            return False

    def get_device_time(self) -> datetime:
        """
        Fetches the current time directly from the emulator.

        FIX #4: on parse failure the original code silently returned datetime.now()
        (the host PC time), which could cause incorrect timestamps to be written
        back to the emulator. Now a RuntimeError is raised instead, letting the
        caller handle the failure explicitly and halt the farming loop.

        Raises:
            RuntimeError: if the device time cannot be retrieved or parsed.
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

        FIX #9: coordinates are validated before the command is sent.
        """
        validate_coords(x, y)
        self.run_cmd(f"shell input tap {x} {y}")
        logging.info(f"[ACTION] Tapped coordinates: X={x}, Y={y}")

    def skip_days(self, days_to_skip: int):
        """
        Jumps forward a specified number of days from the emulator's current time.

        FIX #4: if get_device_time() raises RuntimeError the exception propagates
        to the caller, aborting the farming loop instead of silently using PC time.
        """
        current_time = self.get_device_time()   # may raise RuntimeError
        new_time     = current_time + timedelta(days=days_to_skip)
        self.set_device_time(new_time)
        logging.info(f"[ACTION] Skipped forward {days_to_skip} day(s).")

    def apply_fix(self):
        """Reverts the time to yesterday at 23:59 to trigger the calendar fix."""
        real_yesterday = (datetime.now() - timedelta(days=1)).replace(
            hour=23, minute=59, second=0)
        logging.info("[FIX] Reverting time to yesterday 23:59...")
        self.set_device_time(real_yesterday)

    def is_game_foreground(self) -> bool:
        """
        Returns True if the game's Activity is currently in the foreground.

        FIX #5 (race condition): the original code returned on the very first
        line containing 'mResumedActivity', ignoring all subsequent lines.
        If multiple matching lines exist in dumpsys output, the result depended
        on their order rather than actual game state.
        Now all matching lines are checked — True is only returned when at least
        one of them contains the package name.
        """
        output = self.run_cmd("shell dumpsys activity activities")
        for line in output.splitlines():
            if "mResumedActivity" in line or "ResumedActivity" in line:
                if self.package_name in line:
                    return True

        # No matching line contained the package name — check the focused window.
        focused = self.run_cmd("shell dumpsys window windows | grep mCurrentFocus")
        return self.package_name in focused

    def stop_game(self):
        """
        Force-stops the game and waits for confirmation via polling.

        FIX #6: the original code sent the stop command then blindly slept for
        2 seconds with no verification. On slow machines or a hung emulator the
        game could still be running when the script moved on.
        Now polls is_game_foreground() until the game disappears or
        STOP_GAME_TIMEOUT is reached, then logs a warning if it did not stop.
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

    def start_game(self):
        """
        Launches the game using its specific Activity path.

        FIX #10: the original success check looked for the strings 'Complete'
        and 'Status: ok' in the am-start output, which are locale-dependent and
        may not appear on non-English emulator builds.
        Replaced with an is_game_foreground() check after the startup delay,
        which works regardless of the emulator's system language.
        """
        logging.info(f"[ACTION] Launching {self.package_name}...")
        self.run_cmd("shell input keyevent 3")
        time.sleep(1)
        self.run_cmd(
            f"shell am start -S -W -n {self.package_name}/{self.activity_name}"
        )
        # Allow the game time to load, then verify it is actually in the foreground.
        time.sleep(7)
        if self.is_game_foreground():
            logging.info("[SUCCESS] Game launched successfully.")
        else:
            logging.warning(
                "[WARNING] Game not detected in foreground after launch. "
                "Please check the emulator screen."
            )
import tkinter as tk
from tkinter import font as tkfont
import threading
import queue
import json
import os
import sys
import math
import time
import logging
import logging.handlers
import webbrowser
from datetime import datetime
from driver import (GameDriver, validate_adb_address, validate_coords,
                    validate_package_name, validate_activity_name,
                    setup_rotating_log)
import ctypes

myappid = 'arturpen.abtfarmer' 
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
APP_VERSION = "2.2.3"
APP_TITLE   = f"ArturPen's ABT Farmer  v{APP_VERSION}"
CONFIG_FILE = "config.json"
LOG_FILE    = "farm_log.txt"
GITHUB_URL  = "https://github.com/ArturPen/angry-birds-transformers-farmer"

DEFAULT_CONFIG = {
    "adb_address":   "127.0.0.1:5575",
    "package_name":  "com.rovio.angrybirdstransformers",
    "activity_name": "com.rovio.angrybirdstransformers.AngryBirdsTransformersActivity",
    "btn_x": 720,
    "btn_y": 890,
}

DONATE_TON  = "UQB4L-ZzhteBgkQEWqejBkDm4ZKjG0leGJwgfXMy5gfknzQR"
DONATE_USDT = "TEL1XmhnoE6eeudsPEZf3F82bPZMKrrrSd"

# ── Palette ───────────────────────────────────────────────────────────────────
BG         = "#16161e"
SURFACE    = "#1f1f2e"
SURFACE2   = "#2a2a3d"
ACCENT     = "#ff6b35"
ACCENT_DIM = "#7a3318"
STOP_RED   = "#e94560"
STOP_DIM   = "#2e1520"
STOP_DIM_FG= "#6b3040"
TEXT       = "#f0f0f8"
SUBTEXT    = "#8888aa"
SUCCESS    = "#4ecca3"
WARNING    = "#ffd166"
ERR        = "#ff4757"
BORDER     = "#2e2e45"
LOG_BG     = "#0d0d18"
LOG_FG     = "#c8c8e8"

# ── Fonts ─────────────────────────────────────────────────────────────────────
F_TITLE  = ("Segoe UI", 13, "bold")
F_BOLD   = ("Segoe UI", 10, "bold")
F_BODY   = ("Segoe UI", 10)
F_SMALL  = ("Segoe UI", 8)
F_MONO   = ("Consolas", 9)
F_LABEL  = ("Segoe UI", 9)

def get_resource_path(relative_path):
    try:
        # PyInstaller creates _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ─────────────────────────────────────────────────────────────────────────────
# Config helpers
# ─────────────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        # FIX #4 (app): specific exceptions instead of a bare pass so the user
        # knows the config could not be read rather than silently getting defaults.
        except json.JSONDecodeError as e:
            logging.warning(f"[CONFIG] config.json is malformed, using defaults: {e}")
        except Exception as e:
            logging.warning(f"[CONFIG] Could not read config.json: {e}")
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# Queue-based logging handler (farming thread -> GUI)
# ─────────────────────────────────────────────────────────────────────────────
class QueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord):
        self.log_queue.put(self.format(record))


# ─────────────────────────────────────────────────────────────────────────────
# Farming worker — runs in a background thread
# ─────────────────────────────────────────────────────────────────────────────
def farming_worker(mode: int, amount: int, cfg: dict,
                   stop_event: threading.Event,
                   log_q: queue.Queue,
                   ctrl_q: queue.Queue):
    """
    mode 1 = Farm Gems   (2-day skip, 5 gems/cycle, min 25 gems)
    mode 2 = Farm Resources (1-day skip, sequential rewards, min 15 days)

    ctrl_q messages:
        "STOP_UNLOCKED"  - stop is now safe to trigger
        "DONE"           - farming finished normally
        "STOPPED"        - farming stopped via stop command (fix executed)
        "ERROR:<msg>"    - fatal error, farming aborted
    """
    # FIX #5 (app): wrap the entire worker in a top-level try/except so that
    # any unhandled exception in the thread sends an ERROR signal to ctrl_q,
    # restoring the UI instead of leaving it stuck in the "farming" state forever.
    try:
        _farming_worker_inner(mode, amount, cfg, stop_event, log_q, ctrl_q)
    except Exception as e:
        logging.exception("[FATAL] Unhandled exception in farming thread")
        ctrl_q.put(f"ERROR:Unexpected error: {e}")


def _farming_worker_inner(mode: int, amount: int, cfg: dict,
                          stop_event: threading.Event,
                          log_q: queue.Queue,
                          ctrl_q: queue.Queue):

    # ── Setup logging ──────────────────────────────────────────────────────
    # Two channels:
    #   logger      -> log_q  (Activity Log in the GUI)   - key events only
    #   file_logger -> farm_log.txt (Extended Log)        - full verbose output
    #
    # FIX (logging): log() now writes to BOTH channels so that everything
    # visible to the user in the GUI is also present in the text log file.
    logger = logging.getLogger("activity")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    file_logger = logging.getLogger("verbose")
    file_logger.setLevel(logging.INFO)
    file_logger.handlers.clear()
    file_logger.propagate = False

    fmt = logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")

    q_handler = QueueHandler(log_q)
    q_handler.setFormatter(fmt)
    logger.addHandler(q_handler)

    # FIX #8: attach a RotatingFileHandler via setup_rotating_log() so the
    # log file is automatically rotated instead of growing without limit.
    setup_rotating_log(LOG_FILE)
    try:
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        file_logger.addHandler(fh)
    except Exception:
        pass

    def log(msg: str):
        """Key event -> Activity Log (GUI) AND farm_log.txt."""
        logger.info(msg)
        file_logger.info(msg)

    def vlog(msg: str):
        """Verbose technical detail -> farm_log.txt only."""
        file_logger.info(msg)

    def logall(msg: str):
        """Important event -> both channels (kept for compatibility)."""
        logger.info(msg)
        file_logger.info(msg)

    # Bridge: driver uses the root logger — redirect its output to file_logger.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.propagate = False

    class BridgeHandler(logging.Handler):
        def emit(self, record):
            file_logger.handle(record)

    root_logger.addHandler(BridgeHandler())

    # ── Connect ────────────────────────────────────────────────────────────
    try:
        driver = GameDriver(
            adb_address=cfg["adb_address"],
            package_name=cfg["package_name"],
            activity_name=cfg["activity_name"],
        )
    # FIX #2 (app): ValueError is now raised by validate_adb_address(),
    # validate_package_name(), and validate_activity_name() in
    # GameDriver.__init__ — catch it here and report a clean error to the UI.
    except ValueError as e:
        ctrl_q.put(f"ERROR:{e}")
        return
    except Exception as e:
        ctrl_q.put(f"ERROR:Failed to create driver: {e}")
        return

    log(f"[INFO] Connecting to {cfg['adb_address']}...")
    if not driver.connect():
        ctrl_q.put("ERROR:Could not connect to the emulator. Check ADB settings.")
        return
    log("[INFO] Connection established.")

    # ── Pre-flight: verify the game is actually running with the configured
    #    package name before touching time or clicking anything.
    #
    #    This catches the most common silent failure: the user saved a wrong
    #    package_name in Settings, so is_game_foreground() would always return
    #    False, causing every cycle to be flagged as a crash immediately.
    #    We surface that as a clear, actionable error instead.

    # ── (Pre-flight) ────────────────────────────────────────
    log("[INFO] Verifying package and activity settings...")

    # 1. Package check — is the app actually installed on the emulator?
    if not driver.verify_package_installed():
        logall(f"[ERROR] Package '{cfg['package_name']}' is NOT installed on the emulator.")
        logall("[ERROR] Please check Settings → Package Name.")
        logall("[ERROR] Make sure the game is installed in BlueStacks.")
        ctrl_q.put(f"ERROR:Package '{cfg['package_name']}' not found on emulator. Check Settings → Package Name.")
        return

    log("[INFO] Package found. Verifying activity...")

    # 2. Activity check — does the configured activity exist inside the package?
    if not driver.verify_activity_exists():
        logall(f"[ERROR] Activity '{cfg['activity_name']}' not found in package '{cfg['package_name']}'.")
        logall("[ERROR] Please check Settings → Activity Name.")
        ctrl_q.put(f"ERROR:Activity '{cfg['activity_name']}' not found in package. Check Settings → Activity Name.")
        return

    log("[INFO] Package and activity verified OK.")

    # ───────────────────────────────────────────────────────────────────────
    log("[INFO] Checking game is in foreground with current package name...")
    if not driver.is_game_foreground():
        logall("[ERROR] Game not detected in foreground.")
        logall(f"[ERROR] Package name used: '{cfg['package_name']}'")
        logall("[ERROR] Possible reasons:")
        logall("[ERROR]   • Wrong Package Name or Activity Name in Settings")
        logall("[ERROR]   • Game is not open / minimized in the emulator")
        logall("[ERROR] Fix: open the game, navigate to Daily Rewards,")
        logall("[ERROR]      then verify Package Name in Settings and try again.")
        ctrl_q.put(
            "ERROR:Game not found in foreground. Wrong package name in Settings, "
            "or the game is not open. See Activity Log for details."
        )
        return
    log("[INFO] Game detected in foreground. Starting farm...")

    BTN_X = int(cfg["btn_x"])
    BTN_Y = int(cfg["btn_y"])

    # ── Calculate loops ────────────────────────────────────────────────────
    if mode == 1:
        loops     = math.ceil(amount / 5)
        mode_name = "Farm Gems (+2 day skip)"
    else:
        loops     = amount
        mode_name = "Farm Resources (+1 day skip)"

    total_sec = loops * 8
    h, rem = divmod(total_sec, 3600)
    m, s   = divmod(rem, 60)
    if h:   est = f"{h}h {m}m {s}s"
    elif m: est = f"{m}m {s}s"
    else:   est = f"{s}s"

    logall("=" * 48)
    logall(f"MODE:   {mode_name}")
    logall(f"LOOPS:  {loops} cycles")
    logall(f"ETA:    ~{est}")
    logall("=" * 48)

    if mode == 1:
        log("[INFO] Stop button unlocks after cycle 5.")
    else:
        log("[INFO] Stop button unlocks after cycle 14.")

    # ── Helper: interruptible sleep ────────────────────────────────────────
    def isleep(seconds: int) -> bool:
        """Sleeps in 1-second intervals. Returns True if stop was requested."""
        for _ in range(seconds):
            if stop_event.is_set():
                return True
            time.sleep(1)
        return False

    # ── Main loop ──────────────────────────────────────────────────────────
    stopped_early = False

    for i in range(loops):
        cycle = i + 1

        # Stop-flag check (only active after the minimum safe cycle count)
        if mode == 1 and i >= 5 and stop_event.is_set():
            stopped_early = True
            break
        if mode == 2 and i >= 14 and stop_event.is_set():
            stopped_early = True
            break

        log(f"── Cycle {cycle}/{loops}")
        vlog(f"── Cycle {cycle}/{loops} ──────────────────────────")

        # Step 1: time skip
        # FIX #1 (app): skip_days() can now raise RuntimeError (driver fix #4).
        # Catch it here and abort with a clean error message instead of
        # letting the thread crash silently.
        try:
            if mode == 1:
                driver.skip_days(2)
            else:
                driver.skip_days(1)
        except RuntimeError as e:
            logall(f"[ERROR] Failed to read device time: {e}")
            ctrl_q.put(f"ERROR:{e}")
            return

        # Step 2: wait for game engine
        interrupted = isleep(5) if (mode == 1 and i >= 5) or (mode == 2 and i >= 14) else not not time.sleep(5)
        if interrupted:
            stopped_early = True
            break

        # Step 2b: freeze / crash check
        if not driver.is_game_foreground():
            logall("[ERROR] Game freeze detected — activity is no longer in foreground.")
            logall("[ERROR] The game may have crashed or an ANR dialog appeared.")
            vlog("[ERROR] Stopping farming loop. Manual intervention required.")
            ctrl_q.put("ERROR:Game froze or crashed during cycle. Check the emulator screen.")
            return

        # Step 3: tap claim button
        # FIX #9 (app): click() can raise ValueError if coordinates are out of
        # range (driver fix #9). Catch and surface it cleanly.
        try:
            driver.click(BTN_X, BTN_Y)
        except ValueError as e:
            logall(f"[ERROR] Invalid claim button coordinates: {e}")
            ctrl_q.put(f"ERROR:{e}")
            return

        # Step 4: animation grace period
        interrupted = isleep(2) if (mode == 1 and i >= 5) or (mode == 2 and i >= 14) else not not time.sleep(2)
        if interrupted:
            stopped_early = True
            break

        # Step 4b: freeze / crash check
        if not driver.is_game_foreground():
            logall("[ERROR] Game freeze detected — activity is no longer in foreground.")
            logall("[ERROR] The game may have crashed or an ANR dialog appeared.")
            vlog("[ERROR] Stopping farming loop. Manual intervention required.")
            ctrl_q.put("ERROR:Game froze or crashed during cycle. Check the emulator screen.")
            return

        # Unlock stop after the minimum number of safe cycles
        if mode == 1 and cycle == 5:
            ctrl_q.put("STOP_UNLOCKED")
            log("[INFO] Cycle 5 complete — Stop is now active.")

        if mode == 2 and cycle == 14:
            ctrl_q.put("STOP_UNLOCKED")
            log("[INFO] Cycle 14 complete — Stop is now active.")

    # ── Finalization ───────────────────────────────────────────────────────
    def run_fix():
        logall("[FIX] Running Time Fix procedure...")
        vlog("[FIX] Force-stopping game...")
        driver.stop_game()
        time.sleep(2)
        vlog("[FIX] Applying time revert to yesterday 23:59...")
        driver.apply_fix()
        time.sleep(2)
        vlog("[FIX] Launching game...")
        driver.start_game()

    if stopped_early:
        logall("[STOP] Stop received. Executing Time Fix before exit...")
        run_fix()
        logall("[STOP] Fix complete. Wait for 00:00 on the map screen.")
        logall("=" * 48)
        ctrl_q.put("STOPPED")
        return

    logall("[+] Farming complete! Running Time Fix...")
    run_fix()
    log("[!] Waiting 25 s for map to load...")
    vlog("[!] Waiting 25 seconds for map to fully load...")
    time.sleep(25)
    logall("=" * 48)
    logall("[SUCCESS] Done. Stay on the map until 00:00.")
    log("The game will sync naturally at midnight.")
    vlog("The game will register a natural day rollover at midnight, restoring cycles.")
    logall("=" * 48)
    ctrl_q.put("DONE")


# ─────────────────────────────────────────────────────────────────────────────
# Helper: flat styled button
# ─────────────────────────────────────────────────────────────────────────────
def make_btn(parent, text, command, bg=ACCENT, fg=TEXT,
             font=F_BOLD, pady=8, padx=18, width=None, cursor="hand2"):
    b = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=fg, font=font,
        relief="flat", bd=0,
        padx=padx, pady=pady,
        activebackground=bg, activeforeground=fg,
        cursor=cursor,
    )
    if width:
        b.config(width=width)
    return b


# ─────────────────────────────────────────────────────────────────────────────
# Main Application Class
# ─────────────────────────────────────────────────────────────────────────────
class ABTFarmerApp(tk.Tk):

    def __init__(self):
        super().__init__()

        self.config_data  = load_config()
        self.log_q:  queue.Queue = queue.Queue()
        self.ctrl_q: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.farming    = False
        self.mode_var   = tk.IntVar(value=1)  # 1 = Gems, 2 = Resources
        self._stop_btn_active = False          # tracks live stop state

        self._setup_window()
        self._build_main_frame()
        self._build_settings_frame()
        self._build_donate_frame()
        self._build_extlog_frame()
        self._extlog_after    = None
        self._extlog_pos      = 0
        self._countdown_after = None
        self._countdown_end   = 0
        self._show_frame(self.main_frame)

    # ── Window setup ──────────────────────────────────────────────────────────
    def _setup_window(self):
        self.title(APP_TITLE)
        self.resizable(True, True)
        self.minsize(540, 660)
        self.configure(bg=BG)

        # Icon setup
        icon_path = get_resource_path("assets/ABTFarmer.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)

                try:
                    from PIL import Image, ImageTk
                    # Loading ICO from Pillow
                    pil_image = Image.open(icon_path)

                    tk_icon_image = ImageTk.PhotoImage(pil_image)
                    self.iconphoto(True, tk_icon_image)

                    self._taskbar_icon_ref = tk_icon_image 
                except ImportError:
                    
                    tk_icon_image = tk.PhotoImage(file=icon_path)
                    self.iconphoto(True, tk_icon_image)
                    self._taskbar_icon_ref = tk_icon_image

            except Exception:
                pass

        w, h = 580, 800
        self.update_idletasks()
        sx = (self.winfo_screenwidth()  - w) // 2
        sy = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{sx}+{sy}")

    # ── Frame switcher ────────────────────────────────────────────────────────
    def _show_frame(self, frame: tk.Frame):
        for f in (self.main_frame, self.settings_frame,
                  self.donate_frame, self.extlog_frame):
            f.place_forget()
        if frame is self.extlog_frame:
            self._start_extlog_tail()
        else:
            self._stop_extlog_tail()
        frame.place(x=0, y=0, relwidth=1, relheight=1)

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN FRAME
    # ─────────────────────────────────────────────────────────────────────────
    def _build_main_frame(self):
        f = tk.Frame(self, bg=BG)
        self.main_frame = f

        # ── Header ────────────────────────────────────────────────────────
        hdr = tk.Frame(f, bg=SURFACE, height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="🤖  ABT Farmer", font=F_TITLE,
                 bg=SURFACE, fg=TEXT).pack(side="left", padx=20, pady=16)
        tk.Label(hdr, text=f"v{APP_VERSION}", font=F_SMALL,
                 bg=SURFACE, fg=SUBTEXT).pack(side="left", pady=20)

        # ── Mode selector ─────────────────────────────────────────────────
        mode_frame = tk.Frame(f, bg=BG)
        mode_frame.pack(fill="x", padx=24, pady=(20, 0))

        tk.Label(mode_frame, text="Farming Mode", font=F_BOLD,
                 bg=BG, fg=TEXT).pack(anchor="w")

        radio_row = tk.Frame(mode_frame, bg=BG)
        radio_row.pack(anchor="w", pady=(8, 0))

        radio_cfg = dict(
            variable=self.mode_var,
            bg=BG, fg=TEXT,
            selectcolor=SURFACE2,
            activebackground=BG,
            activeforeground=TEXT,
            font=F_BODY,
            cursor="hand2",
            command=self._on_mode_change,
        )
        self.rb_gems = tk.Radiobutton(
            radio_row, text="💎  Farm Gems", value=1, **radio_cfg)
        self.rb_gems.pack(side="left")

        tk.Label(radio_row, text="  │  ", bg=BG, fg=BORDER).pack(side="left")

        self.rb_res = tk.Radiobutton(
            radio_row, text="📦  Farm Resources", value=2, **radio_cfg)
        self.rb_res.pack(side="left")

        # ── Amount input ──────────────────────────────────────────────────
        inp_frame = tk.Frame(f, bg=BG)
        inp_frame.pack(fill="x", padx=24, pady=(18, 0))

        self.inp_label_var = tk.StringVar(value="Gems to farm:  (minimum 25)")
        tk.Label(inp_frame, textvariable=self.inp_label_var,
                 font=F_BOLD, bg=BG, fg=TEXT).pack(anchor="w")

        entry_row = tk.Frame(inp_frame, bg=BG)
        entry_row.pack(anchor="w", pady=(6, 0))

        self.amount_entry = tk.Entry(
            entry_row, width=12,
            font=("Segoe UI", 12),
            bg=SURFACE2, fg=TEXT,
            insertbackground=TEXT,
            relief="flat", bd=0,
        )
        self.amount_entry.pack(side="left", ipady=8, ipadx=8)
        self.amount_entry.insert(0, "25")

        self.countdown_label = tk.Label(
            entry_row, text="",
            font=("Segoe UI", 11, "bold"),
            bg=BG, fg=ACCENT,
        )
        self.countdown_label.pack(side="left", padx=(16, 0))

        # Validation message (hidden until needed)
        self.val_label = tk.Label(
            inp_frame, text="", font=F_SMALL,
            bg=BG, fg=WARNING)
        self.val_label.pack(anchor="w", pady=(4, 0))

        # ── Separator ─────────────────────────────────────────────────────
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", padx=24, pady=18)

        # ── START / STOP button ───────────────────────────────────────────
        btn_container = tk.Frame(f, bg=BG)
        btn_container.pack(padx=24, fill="x")

        self.action_btn = make_btn(
            btn_container,
            text="▶   START",
            command=self._on_start,
            bg=ACCENT, fg=TEXT,
            font=("Segoe UI", 12, "bold"),
            pady=12, padx=0,
        )
        self.action_btn.pack(fill="x")

        # Mode-2 hint shown under the stop button
        self.stop_hint = tk.Label(
            btn_container, text="",
            font=F_SMALL, bg=BG, fg=SUBTEXT)
        self.stop_hint.pack(pady=(4, 0))

        # ── Bottom bar ────────────────────────────────────────────────────
        # NOTE: must be packed BEFORE the expanding log area so pack(side="bottom")
        # claims its space correctly in tkinter's layout engine.
        bottom = tk.Frame(f, bg=SURFACE, height=44)
        bottom.pack(fill="x", side="bottom")
        bottom.pack_propagate(False)

        make_btn(bottom, "⚙  Settings", self._open_settings,
                 bg=SURFACE, fg=SUBTEXT, font=F_LABEL,
                 pady=4, padx=14).pack(side="left", padx=8, pady=8)

        make_btn(bottom, "📋  Extended Log", self._open_extlog,
                 bg=SURFACE, fg=SUBTEXT, font=F_LABEL,
                 pady=4, padx=14).pack(side="left", padx=0, pady=8)

        make_btn(bottom, "❤  Donate", self._open_donate,
                 bg=SURFACE, fg=SUBTEXT, font=F_LABEL,
                 pady=4, padx=14).pack(side="right", padx=8, pady=8)

        # ── Log area ──────────────────────────────────────────────────────
        log_outer = tk.Frame(f, bg=SURFACE, bd=0)
        log_outer.pack(fill="both", expand=True, padx=24, pady=(14, 8))

        log_hdr = tk.Frame(log_outer, bg=SURFACE)
        log_hdr.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(log_hdr, text="▸ Activity Log", font=F_LABEL,
                 bg=SURFACE, fg=SUBTEXT).pack(side="left")

        scrollbar = tk.Scrollbar(log_outer, bg=SURFACE, troughcolor=SURFACE)
        scrollbar.pack(side="right", fill="y", padx=(0, 4), pady=(0, 4))

        self.log_text = tk.Text(
            log_outer,
            bg=LOG_BG, fg=LOG_FG,
            font=F_MONO,
            relief="flat", bd=0,
            state="disabled",
            yscrollcommand=scrollbar.set,
            wrap="word",
            padx=10, pady=6,
            cursor="arrow",
        )
        self.log_text.pack(fill="both", expand=True, padx=(4, 0), pady=(0, 4))
        scrollbar.config(command=self.log_text.yview)

        self.log_text.tag_config("info",    foreground=LOG_FG)
        self.log_text.tag_config("success", foreground=SUCCESS)
        self.log_text.tag_config("warning", foreground=WARNING)
        self.log_text.tag_config("error",   foreground=ERR)
        self.log_text.tag_config("stop",    foreground=STOP_RED)
        self.log_text.tag_config("dim",     foreground=SUBTEXT)

    # ─────────────────────────────────────────────────────────────────────────
    # SETTINGS FRAME  (scrollable)
    # ─────────────────────────────────────────────────────────────────────────
    def _build_settings_frame(self):
        f = tk.Frame(self, bg=BG)
        self.settings_frame = f

        # ── Fixed header (not scrolled) ───────────────────────────────────
        hdr = tk.Frame(f, bg=SURFACE, height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        make_btn(hdr, "←", lambda: self._show_frame(self.main_frame),
                 bg=SURFACE, fg=SUBTEXT, font=("Segoe UI", 14),
                 pady=4, padx=16).pack(side="left", padx=4, pady=12)

        tk.Label(hdr, text="Settings", font=F_TITLE,
                 bg=SURFACE, fg=TEXT).pack(side="left", pady=16)

        # ── Scrollable content area ───────────────────────────────────────
        # Canvas + inner Frame is the standard tkinter scrollable pattern.
        scroll_container = tk.Frame(f, bg=BG)
        scroll_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(scroll_container, bg=BG,
                           highlightthickness=0, bd=0)
        vsb = tk.Scrollbar(scroll_container, orient="vertical",
                           command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)

        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Inner frame lives inside the canvas
        body = tk.Frame(canvas, bg=BG)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")

        # Keep inner frame width in sync with canvas width
        def _on_canvas_resize(event):
            canvas.itemconfig(body_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        # Update scroll region when body changes size
        def _on_body_resize(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        body.bind("<Configure>", _on_body_resize)

        # Mouse-wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        # Unbind when leaving this frame so it doesn't affect other frames
        f.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        f.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # ── Fields (inside scrollable body) ──────────────────────────────
        inner = tk.Frame(body, bg=BG)
        inner.pack(fill="x", padx=28, pady=16)

        self._settings_vars = {}

        fields = [
            ("adb_address",   "ADB Address",
             "e.g. 127.0.0.1:5575  (check BlueStacks Advanced settings)"),
            ("package_name",  "Package Name",
             "Default: com.rovio.angrybirdstransformers"),
            ("activity_name", "Activity Name",
             "Default: ...AngryBirdsTransformersActivity"),
        ]

        for key, label, hint in fields:
            self._add_settings_field(inner, key, label, hint)

        # X / Y coordinates
        tk.Label(inner, text="Claim Button Coordinates",
                 font=F_BOLD, bg=BG, fg=TEXT
                 ).pack(anchor="w", pady=(14, 2))
        tk.Label(inner,
            text="Default X=720, Y=890 for 1920x1080. Change if using a different resolution.",
            font=F_SMALL, bg=BG, fg=SUBTEXT, wraplength=460, justify="left"
            ).pack(anchor="w")

        xy_row = tk.Frame(inner, bg=BG)
        xy_row.pack(anchor="w", pady=(6, 0))

        for key, lbl_text in [("btn_x", "X"), ("btn_y", "Y")]:
            grp = tk.Frame(xy_row, bg=BG)
            grp.pack(side="left", padx=(0, 20))
            tk.Label(grp, text=lbl_text, font=F_LABEL, bg=BG, fg=SUBTEXT).pack(anchor="w")
            v = tk.StringVar(value=str(self.config_data.get(key, "")))
            self._settings_vars[key] = v
            e = tk.Entry(grp, textvariable=v, width=7,
                         font=F_BODY, bg=SURFACE2, fg=TEXT,
                         insertbackground=TEXT, relief="flat", bd=0)
            e.pack(ipady=6, ipadx=6)

        # ── Separator ─────────────────────────────────────────────────────
        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=18)

        # ── GitHub link ───────────────────────────────────────────────────
        gh_row = tk.Frame(inner, bg=BG)
        gh_row.pack(anchor="w")
        tk.Label(gh_row, text="🔗  ", font=F_BODY, bg=BG, fg=TEXT).pack(side="left")
        gh_link = tk.Label(gh_row, text="GitHub Repository",
                           font=("Segoe UI", 10, "underline"),
                           bg=BG, fg=ACCENT, cursor="hand2")
        gh_link.pack(side="left")
        gh_link.bind("<Button-1>", lambda e: webbrowser.open(GITHUB_URL))

        # ── Save button ───────────────────────────────────────────────────
        save_btn = make_btn(inner, "💾  Save Settings", self._save_settings,
                            bg=ACCENT, fg=TEXT, font=F_BOLD, pady=10, padx=0)
        save_btn.pack(fill="x", pady=(20, 0))

        self.settings_saved_label = tk.Label(inner, text="",
            font=F_SMALL, bg=BG, fg=SUCCESS)
        self.settings_saved_label.pack(pady=(6, 16))

    def _add_settings_field(self, parent, key, label, hint):
        tk.Label(parent, text=label, font=F_BOLD, bg=BG, fg=TEXT
                 ).pack(anchor="w", pady=(12, 2))
        tk.Label(parent, text=hint, font=F_SMALL, bg=BG, fg=SUBTEXT,
                 wraplength=460, justify="left").pack(anchor="w")
        v = tk.StringVar(value=self.config_data.get(key, ""))
        self._settings_vars[key] = v
        e = tk.Entry(parent, textvariable=v,
                     font=F_BODY, bg=SURFACE2, fg=TEXT,
                     insertbackground=TEXT, relief="flat", bd=0)
        e.pack(fill="x", ipady=7, ipadx=8, pady=(4, 0))

    def _save_settings(self):
        new_cfg = {}
        for key, var in self._settings_vars.items():
            val = var.get().strip()
            if key in ("btn_x", "btn_y"):
                try:
                    new_cfg[key] = int(val)
                except ValueError:
                    self.settings_saved_label.config(
                        text=f"⚠ {key} must be an integer.", fg=WARNING)
                    return
            else:
                new_cfg[key] = val

        # FIX #3 (app): validate the ADB address before writing to config.json
        # so a malformed address cannot break the next program launch.
        try:
            validate_adb_address(new_cfg["adb_address"])
        except ValueError as e:
            self.settings_saved_label.config(text=f"⚠  {e}", fg=WARNING)
            return

        # Validate package name format before saving — a typo here causes the
        # farmer to silently fail to detect the game in foreground checks.
        try:
            validate_package_name(new_cfg["package_name"])
        except ValueError as e:
            self.settings_saved_label.config(text=f"⚠  {e}", fg=WARNING)
            return

        # Validate activity name format before saving.
        try:
            validate_activity_name(new_cfg["activity_name"])
        except ValueError as e:
            self.settings_saved_label.config(text=f"⚠  {e}", fg=WARNING)
            return

        # FIX #9 (app): validate coordinates before saving.
        try:
            validate_coords(int(new_cfg["btn_x"]), int(new_cfg["btn_y"]))
        except ValueError as e:
            self.settings_saved_label.config(text=f"⚠  {e}", fg=WARNING)
            return

        self.config_data.update(new_cfg)
        save_config(self.config_data)
        self.settings_saved_label.config(text="✓ Settings saved.", fg=SUCCESS)
        self.after(2000, lambda: self.settings_saved_label.config(text=""))

    # ─────────────────────────────────────────────────────────────────────────
    # EXTENDED LOG FRAME
    # ─────────────────────────────────────────────────────────────────────────
    def _build_extlog_frame(self):
        f = tk.Frame(self, bg=BG)
        self.extlog_frame = f

        # ── Header ────────────────────────────────────────────────────────
        hdr = tk.Frame(f, bg=SURFACE, height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        make_btn(hdr, "←", lambda: self._show_frame(self.main_frame),
                 bg=SURFACE, fg=SUBTEXT, font=("Segoe UI", 14),
                 pady=4, padx=16).pack(side="left", padx=4, pady=12)

        tk.Label(hdr, text="Extended Log", font=F_TITLE,
                 bg=SURFACE, fg=TEXT).pack(side="left", pady=16)

        make_btn(hdr, "🗑  Clear", self._clear_extlog,
                 bg=SURFACE, fg=SUBTEXT, font=F_SMALL,
                 pady=4, padx=10).pack(side="right", padx=12, pady=16)

        # ── Log area (same style as Activity Log) ─────────────────────────
        log_outer = tk.Frame(f, bg=SURFACE, bd=0)
        log_outer.pack(fill="both", expand=True, padx=24, pady=(14, 8))

        log_hdr = tk.Frame(log_outer, bg=SURFACE)
        log_hdr.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(log_hdr, text=f"▸ {LOG_FILE}", font=F_LABEL,
                 bg=SURFACE, fg=SUBTEXT).pack(side="left")

        scrollbar = tk.Scrollbar(log_outer, bg=SURFACE, troughcolor=SURFACE)
        scrollbar.pack(side="right", fill="y", padx=(0, 4), pady=(0, 4))

        self.extlog_text = tk.Text(
            log_outer,
            bg=LOG_BG, fg=LOG_FG,
            font=F_MONO,
            relief="flat", bd=0,
            state="disabled",
            yscrollcommand=scrollbar.set,
            wrap="word",
            padx=10, pady=6,
            cursor="arrow",
        )
        self.extlog_text.pack(fill="both", expand=True, padx=(4, 0), pady=(0, 4))
        scrollbar.config(command=self.extlog_text.yview)

        self.extlog_text.tag_config("info",    foreground=LOG_FG)
        self.extlog_text.tag_config("success", foreground=SUCCESS)
        self.extlog_text.tag_config("warning", foreground=WARNING)
        self.extlog_text.tag_config("error",   foreground=ERR)
        self.extlog_text.tag_config("stop",    foreground=STOP_RED)
        self.extlog_text.tag_config("dim",     foreground=SUBTEXT)
        self.extlog_text.tag_config("header",  foreground=ACCENT)

    def _open_extlog(self):
        self._show_frame(self.extlog_frame)

    def _extlog_tag(self, line: str) -> str:
        if "[ERROR]" in line or "Error" in line:
            return "error"
        if "[SUCCESS]" in line or "[FIX]" in line or "[+]" in line:
            return "success"
        if "[STOP]" in line:
            return "stop"
        if "[WARNING]" in line or "[!]" in line:
            return "warning"
        if "==" in line or "──" in line:
            return "header"
        if "[INFO]" in line:
            return "dim"
        return "info"

    def _load_extlog_full(self):
        self.extlog_text.config(state="normal")
        self.extlog_text.delete("1.0", "end")
        self._extlog_pos = 0
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                    self._extlog_pos = fh.tell()
                for line in content.splitlines(keepends=True):
                    self.extlog_text.insert("end", line, self._extlog_tag(line))
                self.extlog_text.see("end")
            except Exception:
                pass
        else:
            self.extlog_text.insert("end",
                "No farm_log.txt found yet.\nStart a farm session to generate logs.\n",
                "dim")
        self.extlog_text.config(state="disabled")

    def _start_extlog_tail(self):
        self._load_extlog_full()
        self._tail_extlog()

    def _tail_extlog(self):
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(self._extlog_pos)
                    new_data = fh.read()
                    self._extlog_pos = fh.tell()
                if new_data:
                    self.extlog_text.config(state="normal")
                    for line in new_data.splitlines(keepends=True):
                        self.extlog_text.insert("end", line, self._extlog_tag(line))
                    self.extlog_text.see("end")
                    self.extlog_text.config(state="disabled")
            except Exception:
                pass
        self._extlog_after = self.after(500, self._tail_extlog)

    def _stop_extlog_tail(self):
        if self._extlog_after is not None:
            self.after_cancel(self._extlog_after)
            self._extlog_after = None

    def _clear_extlog(self):
        self.extlog_text.config(state="normal")
        self.extlog_text.delete("1.0", "end")
        self.extlog_text.config(state="disabled")
        try:
            open(LOG_FILE, "w").close()
            self._extlog_pos = 0
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # DONATE FRAME
    # ─────────────────────────────────────────────────────────────────────────
    def _build_donate_frame(self):
        f = tk.Frame(self, bg=BG)
        self.donate_frame = f

        # ── Header ────────────────────────────────────────────────────────
        hdr = tk.Frame(f, bg=SURFACE, height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        make_btn(hdr, "←", lambda: self._show_frame(self.main_frame),
                 bg=SURFACE, fg=SUBTEXT, font=("Segoe UI", 14),
                 pady=4, padx=16).pack(side="left", padx=4, pady=12)

        tk.Label(hdr, text="Support the Project", font=F_TITLE,
                 bg=SURFACE, fg=TEXT).pack(side="left", pady=16)

        # ── Body ──────────────────────────────────────────────────────────
        body = tk.Frame(f, bg=BG)
        body.pack(fill="both", expand=True, padx=28, pady=20)

        tk.Label(body,
            text="If this tool saved you time and gems,\nfeel free to support the project! 🙏",
            font=("Segoe UI", 11), bg=BG, fg=TEXT,
            justify="center").pack(pady=(0, 24))

        self._add_donate_row(body, "🪙  TON",  DONATE_TON)
        self._add_donate_row(body, "💵  USDT (TRC-20)", DONATE_USDT)

        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=28)

        star_row = tk.Frame(body, bg=BG)
        star_row.pack()
        tk.Label(star_row, text="⭐  ", font=("Segoe UI", 12), bg=BG, fg=WARNING
                 ).pack(side="left")
        gh_link = tk.Label(star_row,
            text="Leave a star on GitHub!",
            font=("Segoe UI", 11, "underline"),
            bg=BG, fg=ACCENT, cursor="hand2")
        gh_link.pack(side="left")
        gh_link.bind("<Button-1>", lambda e: webbrowser.open(GITHUB_URL))

    def _add_donate_row(self, parent, title, address):
        grp = tk.Frame(parent, bg=SURFACE, pady=12, padx=14)
        grp.pack(fill="x", pady=(0, 12))

        tk.Label(grp, text=title, font=F_BOLD, bg=SURFACE, fg=TEXT
                 ).pack(anchor="w")

        addr_row = tk.Frame(grp, bg=SURFACE)
        addr_row.pack(fill="x", pady=(6, 0))

        addr_lbl = tk.Label(addr_row,
            text=address,
            font=("Consolas", 9), bg=SURFACE2, fg=LOG_FG,
            padx=8, pady=6, wraplength=370, justify="left")
        addr_lbl.pack(side="left", fill="x", expand=True)

        copy_btn = make_btn(
            addr_row, "Copy",
            command=lambda a=address: self._copy_to_clipboard(a),
            bg=ACCENT, fg=TEXT,
            font=F_SMALL, pady=5, padx=10)
        copy_btn.pack(side="right", padx=(8, 0))

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    # ─────────────────────────────────────────────────────────────────────────
    # Mode change handler
    # ─────────────────────────────────────────────────────────────────────────
    def _on_mode_change(self):
        mode = self.mode_var.get()
        if mode == 1:
            self.inp_label_var.set("Gems to farm:  (minimum 25)")
            if self.amount_entry.get() in ("15", ""):
                self.amount_entry.delete(0, "end")
                self.amount_entry.insert(0, "100")
            self.val_label.config(text="")
        else:
            self.inp_label_var.set("Days to farm:  (minimum 15)")
            if self.amount_entry.get() in ("100", ""):
                self.amount_entry.delete(0, "end")
                self.amount_entry.insert(0, "15")

    # ─────────────────────────────────────────────────────────────────────────
    # Navigation
    # ─────────────────────────────────────────────────────────────────────────
    def _open_settings(self):
        for key, var in self._settings_vars.items():
            var.set(str(self.config_data.get(key, "")))
        self.settings_saved_label.config(text="")
        self._show_frame(self.settings_frame)

    def _open_donate(self):
        self._show_frame(self.donate_frame)

    # ─────────────────────────────────────────────────────────────────────────
    # Farming control
    # ─────────────────────────────────────────────────────────────────────────
    def _on_start(self):
        if self.farming:
            return

        mode = self.mode_var.get()

        try:
            amount = int(self.amount_entry.get().strip())
        except ValueError:
            self.val_label.config(text="⚠  Please enter a valid number.", fg=WARNING)
            return

        if mode == 1 and amount < 25:
            self.val_label.config(
                text="⚠  Gems mode requires at least 25 gems.\n"
                     "   The Time Fix needs a minimum of 5 skips to work correctly.",
                fg=WARNING)
            return

        if mode == 2 and amount < 15:
            self.val_label.config(
                text="⚠  Resources mode requires at least 15 days.\n"
                     "   The Time Fix needs a minimum of 14 skips to work correctly.",
                fg=WARNING)
            return

        # FIX #2 (app): validate coordinates before starting the thread so
        # a clear error is shown in the GUI rather than failing inside the worker.
        try:
            validate_coords(
                int(self.config_data["btn_x"]),
                int(self.config_data["btn_y"]),
            )
        except (ValueError, KeyError) as e:
            self.val_label.config(
                text=f"⚠  Invalid claim button coordinates: {e}\n"
                     "   Please fix them in Settings.",
                fg=WARNING)
            return

        self.val_label.config(text="")
        self._start_farming(mode, amount)

    def _start_farming(self, mode: int, amount: int):
        self.farming = True
        self.stop_event.clear()
        self._stop_btn_active = False

        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

        self.action_btn.config(
            text="⏹  STOP",
            command=self._on_stop,
        )
        self._update_stop_btn_state()

        if mode == 2:
            self.stop_hint.config(
                text="Stop will unlock after cycle 14", fg=SUBTEXT)
        else:
            self.stop_hint.config(
                text="Stop will unlock after cycle 5", fg=SUBTEXT)

        self.rb_gems.config(state="disabled")
        self.rb_res.config(state="disabled")
        self.amount_entry.config(state="disabled")

        t = threading.Thread(
            target=farming_worker,
            args=(mode, amount, dict(self.config_data),
                  self.stop_event, self.log_q, self.ctrl_q),
            daemon=True,
        )
        t.start()

        self._total_cycles  = math.ceil(amount / 5) if mode == 1 else amount
        self._done_cycles   = 0
        self._current_mode  = mode
        total_sec           = self._total_cycles * 8
        self._countdown_end = time.time() + total_sec
        self._tick_countdown()
        self._poll_queues()

    def _on_stop(self):
        if not self.farming or not self._stop_btn_active:
            return
        self.stop_event.set()
        self.action_btn.config(text="⏳  Stopping...", state="disabled",
                               bg=SURFACE2, fg=SUBTEXT)
        self.stop_hint.config(text="Running Time Fix before exit...", fg=SUBTEXT)

    def _update_stop_btn_state(self):
        if self._stop_btn_active:
            self.action_btn.config(
                bg=STOP_RED, fg=TEXT,
                activebackground=STOP_RED,
                state="normal",
            )
        else:
            self.action_btn.config(
                bg=STOP_DIM, fg=STOP_DIM_FG,
                activebackground=STOP_DIM,
                state="disabled",
            )

    def _on_farming_ended(self):
        """Resets the UI after farming finishes (normally or via stop)."""
        self.farming = False
        self._stop_btn_active = False

        if self._countdown_after is not None:
            self.after_cancel(self._countdown_after)
            self._countdown_after = None
        self.countdown_label.config(text="")

        self.action_btn.config(
            text="▶   START",
            command=self._on_start,
            bg=ACCENT, fg=TEXT,
            activebackground=ACCENT,
            state="normal",
        )
        self.stop_hint.config(text="")

        self.rb_gems.config(state="normal")
        self.rb_res.config(state="normal")
        self.amount_entry.config(state="normal")

    # ─────────────────────────────────────────────────────────────────────────
    # Countdown timer
    # ─────────────────────────────────────────────────────────────────────────
    def _tick_countdown(self):
        if not self.farming:
            return
        remaining = max(0, int(self._countdown_end - time.time()))
        h, rem = divmod(remaining, 3600)
        m, s   = divmod(rem, 60)
        if h:
            text = f"⏱ {h}h {m:02d}m {s:02d}s"
        elif m:
            text = f"⏱ {m}m {s:02d}s"
        else:
            text = f"⏱ {s}s"
        self.countdown_label.config(text=text)
        self._countdown_after = self.after(1000, self._tick_countdown)

    # ─────────────────────────────────────────────────────────────────────────
    # Queue polling
    # ─────────────────────────────────────────────────────────────────────────
    def _poll_queues(self):
        # Drain the log queue
        try:
            while True:
                msg = self.log_q.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass

        # Drain the control queue
        try:
            while True:
                cmd = self.ctrl_q.get_nowait()
                if cmd == "STOP_UNLOCKED":
                    self._stop_btn_active = True
                    self._update_stop_btn_state()
                    self.stop_hint.config(
                        text="Stop is now active", fg=SUCCESS)
                elif cmd in ("DONE", "STOPPED"):
                    self._on_farming_ended()
                    return
                elif cmd.startswith("ERROR:"):
                    self._append_log(f"[ERROR] {cmd[6:]}", tag="error")
                    self._on_farming_ended()
                    return
        except queue.Empty:
            pass

        if self.farming:
            self.after(80, self._poll_queues)

    # ─────────────────────────────────────────────────────────────────────────
    # Log helpers
    # ─────────────────────────────────────────────────────────────────────────
    def _append_log(self, msg: str, tag: str = None):
        if tag is None:
            if "[ERROR]" in msg or "Error" in msg:
                tag = "error"
            elif "[SUCCESS]" in msg or "[FIX]" in msg:
                tag = "success"
            elif "[STOP]" in msg:
                tag = "stop"
            elif "[INFO]" in msg or "──" in msg or "==" in msg:
                tag = "dim"
            else:
                tag = "info"

        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n", tag)
        self.log_text.see("end")
        self.log_text.config(state="disabled")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    app = ABTFarmerApp()
    app.mainloop()
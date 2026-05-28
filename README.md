# AB Transformers Automated Time-Skip Glitch 🤖⚡

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![ADB](https://img.shields.io/badge/ADB-Android%20Debug%20Bridge-green.svg)](https://developer.android.com/tools/adb)
[![BlueStacks 5](https://img.shields.io/badge/BlueStacks-5-blue.svg)](https://www.bluestacks.com/)
![Downloads](https://img.shields.io/github/downloads/ArturPen/angry-birds-transformers-farmer/total)

A fully automated Python tool for the **Ultimate Time-Skip Glitch** in Angry Birds Transformers. Connects to a rooted emulator via ADB, manipulates the system clock to farm gems and resources infinitely, and safely restores the calendar sync without bricking your game timers.

**Original Method & Exploit Guide:** [Reddit - Ultimate Guide](https://www.reddit.com/r/angrybirdstransform/comments/1ssj9wo/ultimate_guide_time_skip_glitch_in_angry_birds/)

**YouTube script setup guide:** [YouTube - ABTFarmer](https://youtu.be/T9emM1sBUwM)

**YouTube root guide:** [YouTube - Bluestacks 5 root](https://youtu.be/ba7RhQqyhPk?si=Fgh32wgzkYv9ACLJ)

**Contact developer:** [Google forms](https://forms.gle/yWmTFcr9sMUAjid26)

---

## ⚠️ Disclaimer

This tool, ABTFarmer, is provided for educational and research purposes only. The author assumes no responsibility for any consequences resulting from the use of this software.
* Account Safety: Using this tool violates the Terms of Service of the game. You acknowledge that your account may be permanently banned by the game developers.
* No Warranty: This software is provided "as is" without any warranties of any kind, express or implied. The author does not guarantee that the tool will work as intended or that it will be free from bugs.
* Non-Affiliation: This project is not affiliated with, authorized, maintained, or endorsed by Rovio Entertainment or any of its affiliates. All game assets and trademarks are the property of their respective owners.

By using ABTFarmer, you agree to take full responsibility for any damage to your device or loss of game data.

---

## ❤️ Support

If this tool saved you time and gems, feel free to support the project!

### 🪙 Donate via Crypto

* **TON:** `UQB4L-ZzhteBgkQEWqejBkDm4ZKjG0leGJwgfXMy5gfknzQR`
* **USDT (TRC-20):** `TEL1XmhnoE6eeudsPEZf3F82bPZMKrrrSd`

### ⭐ GitHub Star

* **Leave a ⭐ if you find this project useful!**

---

## 🖥️ GUI Overview

 `app.py` launches a dark-themed desktop window (`ABTFarmerApp`) built with Python's built-in `tkinter` library. No additional libraries need to be installed.

The interface is organized into four screens navigated via buttons in the bottom bar and headers:

**Main Screen** — the primary farming control panel:
- **Farming Mode** radio buttons: `💎 Farm Gems` or `📦 Farm Resources`
- **Amount input field** — enter the number of gems or days to farm (with live validation)
- **▶ START / ⏹ STOP button** — a single button that changes state. The STOP button is intentionally disabled at the start of a session and only activates after enough safe cycles have been completed (cycle 5 for Gems mode, cycle 14 for Resources mode), preventing a partial fix from breaking your calendar
- **Activity Log** — a color-coded, scrollable real-time log embedded in the main window. Key farming events (cycle starts, fix stages, errors) are shown with distinct colors: teal for success, yellow for warnings, red for errors

**Settings Screen** — configure the tool without editing any files:
- **ADB Address** — the emulator's ADB port (e.g. `127.0.0.1:5575`)
- **Package Name** — the game's Android package identifier
- **Activity Name** — the specific activity used to launch the game
- **Claim Button Coordinates** — X and Y pixel coordinates of the Claim button. Default is X=720, Y=890 for a 1920×1080 emulator window
- All fields are saved to `config.json` on disk and restored automatically on next launch

**Extended Log Screen** — shows the full verbose output of `farm_log.txt` (every ADB command, time set, cycle detail). The view tails the file live while farming is running, and includes a **Clear** button to wipe the log.

**Donate Screen** — crypto wallet addresses with one-click copy buttons, and a GitHub star link.

<table style="border: none;">
  <tr>
    <td style="border: none;"><img src="https://github.com/user-attachments/assets/1b3d36ab-4830-497b-a352-819b047bd4b1" width="400"></td>
    <td style="border: none;"><img src="https://github.com/user-attachments/assets/94b2a2df-2558-4866-b472-96f6856750b6" width="400"></td>
  </tr>
</table>

---

## ⚙️ How It Works (Code Analysis)

The tool relies on `adb shell` and `su` commands to bypass Android's time synchronization. When you start farming from the GUI, the script spawns a background thread that runs the selected mode in a loop while the interface stays responsive.

### Mode 1: Gems Farm (+2 Days Jump)

* **Goal:** Maximize Gems output.
* **How it works:** The script skips 2 days into the future on every cycle. This breaks your login streak, forcing the game to give you the "Day 1" reward (always 5 Gems).
* **Input:** Enter the **total amount of gems** you want. The script calculates the required loops automatically (`ceil(gems / 5)`).
* **Minimum:** 25 gems (requires at least 5 cycles for the Time Fix to work correctly).
* **Stop unlocks:** after cycle 5.

### Mode 2: Resources Farm (+1 Day Jump)

* **Goal:** Collect sequential weekly rewards (Pigs, Coins, and Day-7 Crystals).
* **How it works:** The script skips exactly 1 day into the future per cycle, maintaining your daily login streak and letting you collect the full 7-day calendar rewards sequentially.
* **Input:** Enter the **number of days (claims)** to process.
* **Minimum:** 15 days (requires at least 14 cycles for the Time Fix to work correctly).
* **Stop unlocks:** after cycle 14.

### The "Time Fix"

Once farming is done (or you press Stop after it unlocks):

1. The script force-stops the game completely.
2. It sets the emulator's clock to **23:59 of the previous real-world day**.
3. It launches the game and waits.
4. **Your only job:** watch the map screen until the clock hits exactly `00:00`. The game registers a natural day rollover, permanently fixing the calendar.

After a full farming session (not an early stop), the script also waits 25 seconds for the map to load before showing the final success message.

---

## 🛠 Prerequisites & Emulator Setup

To change the system date, Android **requires Root access**. The tool will not work on an unrooted emulator.

## Required Software
### Open source
| Software | Purpose |
|----------|---------|
| **[Source code](https://github.com/ArturPen/angry-birds-transformers-farmer/)** | Download source code of ABTFarmer |
| **[Python 3.8+](https://www.python.org/)** | No external libraries required; only built-in modules are used (`tkinter`, `threading`, `json`, `logging`, etc.) |
| **[BlueStacks 5](https://www.bluestacks.com/)** | Recommended emulator |
| **[Magisk 27](https://youtu.be/ba7RhQqyhPk?si=Fgh32wgzkYv9ACLJ)** | Required utility to unlock Root access in BlueStacks |
| **[ADB files](https://developer.android.com/tools/adb)** | `adb.exe`, `AdbWinApi.dll`, `AdbWinUsbApi.dll` must be placed in the same folder as `app.py` and `driver.py` |
### Download ABTFarmer.exe from [Releases](https://github.com/ArturPen/ab-transformers-time-skip/releases)
| Software | Purpose |
|----------|---------|
| **[ABTFarmer.exe](https://github.com/ArturPen/ab-transformers-time-skip/releases)** | Compiled exe  |
| **[BlueStacks 5](https://www.bluestacks.com/)** | Recommended emulator |
| **[Magisk 27](https://youtu.be/ba7RhQqyhPk?si=Fgh32wgzkYv9ACLJ)** | Required utility to unlock Root access in BlueStacks |

---
### Rooting & ADB Configuration

1. Open **[YouTube rooting guide](https://youtu.be/ba7RhQqyhPk?si=Fgh32wgzkYv9ACLJ)**, and follow the instructions to unlock and patch Root access.
2. In BlueStacks, go to **Settings → Advanced** (or Developer Options).
3. Toggle on **Android Debug Bridge (ADB)**.
4. Note your ADB port — usually `127.0.0.1:5575` or `127.0.0.1:5555`.

---

## 🚀 Installation & Usage
## Open source
### Step 1: Clone the repository

```bash
git clone https://github.com/ArturPen/ab-transformers-time-skip.git
cd ab-transformers-time-skip
```

### Step 2: Place ADB files

Put `adb.exe`, `AdbWinApi.dll`, and `AdbWinUsbApi.dll` in the same folder as `app.py` and `driver.py`. The tool locates ADB automatically.

### Step 3: Open program and configure settings

Launch the app.py and open **⚙ Settings**. Set your ADB address to match the port shown in BlueStacks Advanced settings. The default is `127.0.0.1:5575`.

If your emulator resolution is not 1920×1080, adjust the **Claim Button X/Y coordinates** to match the pixel position of the Claim button on your screen or choose 1920x1080 resolution in BlueStacks 5 advanced settings. Click **💾 Save Settings** — everything is written to `config.json` and restored on the next launch.

### Step 4: Start farming
* Open the game on rooted emulator, log in to the game, open daily rewards menu
* Select your farming mode, enter the desired amount, and press **▶ START**.

## Download ABTFarmer.exe
### Step 1: Download ABTFarmer.exe from [Releases](https://github.com/ArturPen/ab-transformers-time-skip/releases)
### Step 2: Open program and configure settings

Launch the ABTFarmer.exe and open **⚙ Settings**. Set your ADB address to match the port shown in BlueStacks Advanced settings. The default is `127.0.0.1:5575`.

If your emulator resolution is not 1920×1080, adjust the **Claim Button X/Y coordinates** to match the pixel position of the Claim button on your screen or choose 1920x1080 resolution in BlueStacks 5 advanced settings. Click **💾 Save Settings** — everything is written to `config.json` and restored on the next launch..

### Step 3: Start farming
* Open the game on rooted emulator, log in to the game, open daily rewards menu
* Select your farming mode, enter the desired amount, and press **▶ START**.

---

## 📝 Features & Logging

### Two farming modes
Gems-focused or resource-focused — each with its own skip strategy and loop calculation.

### Estimated time display
Before the loop starts, the script prints how long the full run will take based on an average cycle time of ~8 seconds.

### Graphical Interface

A dark-themed window centers itself on launch and is fully resizable. Text is DPI-aware on Windows high-resolution displays.

### Two-Channel Logging

Log output is split into two separate streams:

* **Activity Log** (in the GUI) — shows compact, key-event messages: cycle numbers, Fix stages, errors, and final status. Color-coded by event type.
* **Extended Log** (`farm_log.txt` + in-app viewer) — records every ADB command, time manipulation, and verbose cycle detail. The in-app Extended Log screen tails the file in real time (polling every 500ms) while farming is active.

### Persistent Configuration

All settings (ADB address, package name, activity name, button coordinates) are saved to `config.json` next to the script and loaded automatically on startup. No need to edit source files between sessions.

### Safe Stop Mechanism

| Mode | When `stop` becomes available |
|------|-------------------------------|
| Mode 1 | Gems Farm | From cycle 5 |
| Mode 2 | Resources Farm | From cycle 14 |

The STOP button is visually disabled (dimmed) at the start of every session and only becomes active once the minimum number of cycles required for a valid Time Fix has been completed. Pressing Stop triggers the full Time Fix procedure before exiting — the game is force-stopped, the clock is reverted to yesterday at 23:59, and the game is relaunched.

### Auto-Recovery

On connect, the driver immediately disables Android's `auto_time` global setting so the emulator does not fight the script during date manipulation.

### Direct Activity Launching

Uses native Android intents (`am start -S -W -n`) to wake the game directly, bypassing suspended tab issues.

### Countdown Timer:

Displays the estimated time remaining next to the amount input field. Updates live every second while farming is active.

### Interruptible Sleep

All wait periods inside the farming loop are split into 1-second intervals. Once Stop is unlocked, each wait checks the stop flag every second, so the script reacts to a stop request immediately rather than waiting out a full delay.

### Smart Crash & Background Detection

The program monitors the game process in real-time. If the game crashes or is minimized, the farmer will automatically stop to prevent accidental clicks on your desktop or emulator home screen. Information about the crash will go to logs.

---

## 📝 Logging Reference

All messages follow the format `HH:MM:SS [LEVEL] message`. Key entries:

| Entry | Meaning |
|-------|---------|
| `[ACTION] Skipped forward N day(s)` | Time jump executed |
| `[TIME] Device time set to: DD.MM.YYYY HH:MM` | Clock confirmed |
| `[ACTION] Tapped coordinates: X=720, Y=890` | Claim button pressed |
| `[FIX] Reverting time to yesterday 23:59` | Time Fix started |
| `[SUCCESS] Game launched successfully` | Game is running |
| `[STOP] Program was stopped via the 'stop' command.` | Manual stop recorded |
| `[ERROR] Game freeze detected — activity is no longer in foreground.` | Game crash detected |

---

## ⚠️ Antivirus Notice
Some antivirus software (like Windows Defender) may flag the `.exe` version as a false positive. This happens because:
1. The app is bundled using **PyInstaller**, which is sometimes flagged by heuristic engines.
2. The app uses **ADB (Android Debug Bridge)** to communicate with your emulator.

**Is it safe?** Yes. You can check the source code yourself—the app only interacts with ADB and your game. If your antivirus blocks the app, please choose "start anyway", add it to the **exclusions list** or run the script version directly using Python.

UPD: virustotal is marking this program probalby for using root in emulator and adb: [virustotal](https://www.virustotal.com/gui/file/0a0a5c29ded4e2b5706936203f0a0702b5a1d7ad0ceb48abc6ccbac574c79231)

---

*Developed by [ArturPen](https://github.com/ArturPen)*

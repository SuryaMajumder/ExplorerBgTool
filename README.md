# 🖼️ Explorer Background Tool

Set a **custom background image** in Windows File Explorer — with live preview, brightness, blur, opacity controls, and auto-start on boot.

Built with Python + a browser-based UI. Works on **Windows 10 and Windows 11**.

> ⚠️ This tool uses a DLL hook to inject a background into Explorer. It works great but Microsoft occasionally patches these hooks in major Windows Updates — if your background disappears after an update, just click Apply again in the app.

---

## 📸 Preview

```
┌─────────────────────────────────────────────────────────┐
│  > This PC                          🔍 Search This PC   │
├─────────────────┬───────────────────────────────────────┤
│ 🏠 Home         │                                        │
│ 🖼️  Gallery     │   [ Your beautiful image fills here ]  │
│                 │                                        │
│ 📁 Desktop      │      🌸 anime / artwork / photo        │
│ 📁 Documents    │                                        │
│ 📁 Downloads    │                                        │
└─────────────────┴───────────────────────────────────────┘
```

---

## ✅ Requirements

| Requirement | How to get it |
|---|---|
| **Windows 10 or 11** | You already have it 😄 |
| **Python 3.8+** | [python.org/downloads](https://python.org/downloads) |
| **Pillow** | Auto-installed by `start.bat` |

> 🔴 **Critical during Python install:** Check **"Add Python to PATH"**
> ```
> ☑  Add Python to PATH   ← tick this, it's unchecked by default!
> ```

---

## 📦 What's in this repo

**Right after cloning:**
```
ExplorerBgTool/
│
├── 📄 explorer_bg_tool.py      ← The main app (Python)
├── 📄 ExplorerBgTool.dll       ← The DLL that hooks into Explorer
│
├── 🖱️ start.bat                ← START HERE — launches the control panel
├── 🖱️ SETUP_AUTOSTART.bat      ← Run once to survive reboots
├── 📄 setup_autostart.ps1      ← Called by SETUP_AUTOSTART.bat (don't delete)
├── 🖱️ REMOVE_AUTOSTART.bat     ← Removes auto-start if you want to undo
│
└── 📄 README.md                ← You are here!
```

**After running the app for the first time, these appear automatically:**
```
ExplorerBgTool/
│
├── 📄 bg_config.json           ← Your saved settings (auto-created)
├── 📄 launch_bg_silent.vbs     ← Silent boot launcher (auto-created by SETUP_AUTOSTART)
└── 📁 image/
    └── 🖼️ bg_custom.png        ← Your processed background (auto-created)
```

---

## 🚀 Setup Guide

### Step 1 — Clone the repo

```bash
git clone https://github.com/SuryaMajumder/ExplorerBgTool.git
```

Or click **Code → Download ZIP** on GitHub and extract it anywhere (Desktop, C drive, wherever).

---

### Step 2 — Launch the control panel

Double-click **`start.bat`**

```
start.bat
 └─→ asks for admin privileges → click Yes
     └─→ auto-installs Pillow if missing
         └─→ opens your browser at http://127.0.0.1:57821
```

> 💡 The CMD window that opens must stay open in the background — it's the server powering the browser UI. Don't close it while using the app.

The browser control panel looks like this:

```
┌─────────────────────────────────────────────────────────────────────┐
│  🖼️  Explorer Background Tool                    ✓ Administrator    │
├──────────────────────────────────┬──────────────────────────────────┤
│                                  │  IMAGE POSITION                  │
│  [ Live Preview of your image ]  │  ↖ Top Left   ↗ Top Right       │
│                                  │  ↙ Bot Left   ↘ Bot Right       │
│   Updates in real time as you    │  ⊙ Center     ⤢ Stretch         │
│   move the sliders below!        │  ⊞ Zoom & Fill  ← recommended!  │
│                                  ├──────────────────────────────────┤
├──────────────────────────────────┤  EXPLORERTOOL DLL               │
│  IMAGE                           │  [ ExplorerBgTool.dll ] [Browse] │
│  [ your-image.jpg ]  [ Browse ]  ├──────────────────────────────────┤
│                                  │  ACTIONS                         │
│  ADJUSTMENTS                     │                                  │
│  ✨ Brightness  ───●─────  1.0×  │  ✅  Apply to Explorer           │
│  🌫️ Blur/Haze   ●─────────  0px  │  🔄  Restart Explorer            │
│  💧 Opacity     ──────●──   81   │  ❌  Uninstall Background        │
└──────────────────────────────────┴──────────────────────────────────┘
```

---

### Step 3 — Pick your image

Click **Browse** under the **IMAGE** section and select any image file:

| Supported formats |
|---|
| `.png` `.jpg` `.jpeg` `.webp` `.bmp` |

The **Live Preview** box updates instantly — what you see there is exactly what Explorer will show.

---

### Step 4 — Adjust to your taste

| Slider | What it does | Sweet spot |
|---|---|---|
| **✨ Brightness** | Makes the image lighter or darker | `0.4–0.7×` — dim it so folder icons stay readable |
| **🌫️ Blur / Haze** | Adds a frosted-glass dreamy haze | `3–8px` for a subtle glow effect |
| **💧 Opacity** | How see-through the image is | `80–180` balances beauty and readability |

> 💡 Watch the Live Preview as you drag — it updates after you release the slider. (P.S.: Dark Mode of Windows gives better vibe with it than Light mode.)

---

### Step 5 — Choose image position

| Option | What it does | When to use it |
|---|---|---|
| ↖ Top Left | Anchors to top-left, no scaling | Fixed decorative corner image |
| ↗ Top Right | Anchors to top-right, no scaling | Fixed decorative corner image |
| ↙ Bot Left | Anchors to bottom-left, no scaling | Fixed decorative corner image |
| ↘ Bot Right | Anchors to bottom-right, no scaling | Fixed decorative corner image |
| ⊙ Center | Centers the image, no scaling | Small icons or logos |
| ⤢ Stretch | Stretches to fill the window | May distort the image |
| **⊞ Zoom & Fill** | **Scales to always fill — no cutoff** | **Use this! Best for photos & artwork** |

> ✅ **Recommendation: always use Zoom & Fill.** It makes the image resize perfectly with your Explorer window no matter how you drag or snap it. Unless using anime figures which stays at fixed positions.

---

### Step 6 — Point to the DLL

Under **EXPLORERTOOL DLL**, click **Browse** and select `ExplorerBgTool.dll` from your folder.

> You only need to do this once. The path is saved in `bg_config.json` automatically.

---

### Step 7 — Apply!

1. Click **✅ Apply to Explorer**
   - A green message appears: *"Applied! Now restart Explorer."*
2. Click **🔄 Restart Explorer**
   - This briefly closes and reopens Explorer (all windows will flash — that's normal)

Open File Explorer and enjoy your background! 🎉

> 💡 Note background doesn't appear at Home and Gallery of File Explorer. You can browse to any other location and your background will appear.

---

## 🔁 Making it survive reboots (do this once)

By default the background resets when you restart Windows. Run this once to fix that:

**Prerequisites:** Complete Steps 2–7 above first so `bg_config.json` exists.

1. Double-click **`SETUP_AUTOSTART.bat`**
2. Click **Yes** on the admin prompt
3. A green message confirms: **"Done! Background will now auto-apply on every login."**

To verify it worked:
- Press `Win + R` → type `taskschd.msc` → hit Enter
- Look for **ExplorerBgTool** in the Task Scheduler list

```
Task Scheduler Library
└── ✅ ExplorerBgTool   ← if this is here, you're done!
```

From now on your background applies silently every time you log into Windows — no CMD window, no browser, just instant background. Exactly like a wallpaper.

---

## 🔄 Changing your background later

Just run `start.bat` anytime:

```
start.bat → Browse new image → adjust sliders → ✅ Apply → 🔄 Restart Explorer
```

Settings save automatically. No need to run SETUP_AUTOSTART again.

---

## ❌ Removing the background

### Option A — Temporarily remove from the app
```
start.bat → ❌ Uninstall Background → 🔄 Restart Explorer
```

### Option B — Remove auto-start too (full uninstall)
```
1. start.bat → ❌ Uninstall Background → 🔄 Restart Explorer
2. Double-click REMOVE_AUTOSTART.bat → click Yes
```

### Option C — Emergency (Explorer crashes on open)

If Explorer keeps crashing after a Windows Update broke the hook:

```
1. Hold ESC and click Explorer in the taskbar
   └─→ This opens Explorer WITHOUT loading the background

2. Run start.bat → ❌ Uninstall Background

3. 🔄 Restart Explorer
```

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| `start.bat` closes instantly | Python not installed, or "Add to PATH" wasn't checked during install |
| Browser doesn't open | Manually go to `http://127.0.0.1:57821` in your browser |
| Top-right badge says "Not Admin" | Close and re-run `start.bat` — click Yes on the UAC prompt |
| "regsvr32 failed" error | You're not running as admin — re-run `start.bat` and click Yes |
| Background disappeared after Windows Update | Run `start.bat` → Apply → done |
| Explorer crashes on open | Hold ESC while clicking Explorer → then Uninstall from app |
| Image gets cut off at window edges | Switch to **Zoom & Fill** position in the app |

---

## 📁 File reference

| File | Purpose | Safe to delete? |
|---|---|---|
| `explorer_bg_tool.py` | Main Python app | ❌ No |
| `ExplorerBgTool.dll` | Explorer hook DLL | ❌ No |
| `start.bat` | Launches control panel | ❌ No |
| `SETUP_AUTOSTART.bat` | Sets up boot auto-start | ✅ After running once |
| `setup_autostart.ps1` | Called by SETUP_AUTOSTART | ❌ Keep alongside the BAT |
| `REMOVE_AUTOSTART.bat` | Removes boot auto-start | ✅ Optional to keep |
| `bg_config.json` | Saved settings | ❌ No (holds your DLL path etc.) |
| `launch_bg_silent.vbs` | Silent boot launcher | ❌ No (needed for auto-start) |
| `image/bg_custom.png` | Processed background copy | ❌ No (re-created on Apply) |

---

## 💡 Pro tips

- Combine **low brightness + slight blur** for a gorgeous frosted glass look
- The app processes your image before applying — your original file is never modified
- You can keep multiple images and swap them anytime via the app
- GIF and live wallpapers are **not supported** inside Explorer (Windows limitation)
- If you move the folder to a new location, just run `start.bat`, click Browse DLL to repoint to the DLL, Apply, then run `SETUP_AUTOSTART.bat` again

---

## 🙏 Credits

- **[Maplespe](https://github.com/Maplespe/explorerTool)** — for the original `ExplorerBgTool.dll` that makes all of this possible
- Python GUI, browser UI, and tooling built on top of it

---

## 📄 License

MIT — do whatever you want with the Python and BAT code.
The `ExplorerBgTool.dll` belongs to [Maplespe](https://github.com/Maplespe/explorerTool) under their original license.

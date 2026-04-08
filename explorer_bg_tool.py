"""
Explorer Background Tool - Browser-based GUI
Supports background image + multiple foreground overlays with individual controls.
Run as Administrator. Requires: pip install pillow
"""

import os, sys, json, base64, subprocess, threading, webbrowser, io, uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from PIL import Image, ImageEnhance, ImageFilter

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "bg_config.json")
PORT        = 57821

# Canvas size we composite onto before sending to Explorer
CANVAS_W, CANVAS_H = 3840, 2160

# ── Wallpaper watcher state ───────────────────────────────────────────────────
_watcher_thread   = None
_watcher_stop     = threading.Event()
_last_wallpaper_mtime = None


def get_transcoded_mtime():
    path = os.path.expandvars(r"%AppData%\Microsoft\Windows\Themes\TranscodedWallpaper")
    try:
        return os.path.getmtime(path)
    except:
        return None


def wallpaper_watcher_loop(handler_cfg_ref, interval=10):
    global _last_wallpaper_mtime
    print("[watcher] Wallpaper watcher started (interval: 30min)")
    while not _watcher_stop.is_set():
        # Wait in small increments so stop event is responsive
        for _ in range(interval * 2):
            if _watcher_stop.is_set():
                break
            _watcher_stop.wait(0.5)

        if _watcher_stop.is_set():
            break

        # Only run if wallpaper mode still active
        if not handler_cfg_ref.get("wallpaper_mode"):
            continue

        mtime = get_transcoded_mtime()
        if mtime and mtime != _last_wallpaper_mtime:
            print("[watcher] Wallpaper changed! Re-applying...")
            _last_wallpaper_mtime = mtime
            try:
                # Re-copy wallpaper
                path = get_desktop_wallpaper()
                if not path:
                    continue
                handler_cfg_ref["image_path"] = path
                save_config(handler_cfg_ref)

                # Re-composite and apply
                dll = handler_cfg_ref.get("dll_path", "")
                if not dll or not os.path.exists(dll):
                    continue
                dll_dir   = os.path.dirname(dll)
                image_dir = os.path.join(dll_dir, "image")
                ini_path  = os.path.join(dll_dir, "config.ini")
                save_final_image(handler_cfg_ref, image_dir)
                write_ini(ini_path, 6, image_dir, handler_cfg_ref.get("folder_ext", False))
                register_dll(dll)
                print("[watcher] Auto-applied new wallpaper!")
            except Exception as e:
                print(f"[watcher] Error: {e}")

    print("[watcher] Watcher stopped.")


def start_watcher(cfg_ref):
    global _watcher_thread, _watcher_stop, _last_wallpaper_mtime
    _watcher_stop.clear()
    _last_wallpaper_mtime = get_transcoded_mtime()
    _watcher_thread = threading.Thread(
        target=wallpaper_watcher_loop,
        args=(cfg_ref,),
        daemon=True
    )
    _watcher_thread.start()


def stop_watcher():
    global _watcher_stop
    _watcher_stop.set()


DEFAULT_CONFIG = {
    "image_path": "", "brightness": 1.0, "blur": 0,
    "contrast": 1.0,  "opacity": 255,    "pos_type": 6,  "dll_path": "",
    "overlays": [],  # list of overlay dicts
    "wallpaper_mode": False,  # True = auto-sync with desktop wallpaper
    "folder_ext": False  # True = also apply to file picker dialogs
}

DEFAULT_OVERLAY = {
    "id": "",           # unique id
    "path": "",         # image path
    "position": "br",   # tl, tr, bl, br
    "scale": 30,        # % of canvas height
    "brightness": 1.0,
    "contrast": 1.0,    # 0.5-2.0
    "blur": 0,
    "opacity": 255,
    "offset_x": 20,    # px padding from edge
    "offset_y": 20,
    "custom_x": -1,    # -1 = use position anchor, 0-100 = % of canvas width
    "custom_y": -1,    # -1 = use position anchor, 0-100 = % of canvas height
    "flip_h": False,
    "flip_v": False,
    "rotation": 0,     # degrees 0-359
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            cfg = json.load(open(CONFIG_FILE))
            for k, v in DEFAULT_CONFIG.items(): cfg.setdefault(k, v)
            return cfg
        except: pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    json.dump(cfg, open(CONFIG_FILE, "w"), indent=2)

# ── Image processing ──────────────────────────────────────────────────────────

def process_layer(src, brightness, blur, opacity, contrast=1.0,
                  flip_h=False, flip_v=False, rotation=0):
    """Load and apply all effects to an image. Returns RGBA."""
    img = Image.open(src).convert("RGBA")
    # Split alpha before any processing so we preserve transparency
    r, g, b, a = img.split()
    rgb = Image.merge("RGB", (r, g, b))
    # Brightness
    rgb = ImageEnhance.Brightness(rgb).enhance(brightness)
    # Contrast
    if contrast != 1.0:
        rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
    # Blur
    if blur > 0:
        rgb = rgb.filter(ImageFilter.GaussianBlur(radius=blur))
        a   = a.filter(ImageFilter.GaussianBlur(radius=blur * 0.5))
    # Opacity
    a = a.point(lambda p: int(p * opacity / 255))
    r2, g2, b2 = rgb.split()
    result = Image.merge("RGBA", (r2, g2, b2, a))
    # Flip
    if flip_h: result = result.transpose(Image.FLIP_LEFT_RIGHT)
    if flip_v: result = result.transpose(Image.FLIP_TOP_BOTTOM)
    # Rotation (expand=True keeps full image, no cropping)
    if rotation != 0:
        result = result.rotate(-rotation, expand=True, resample=Image.BICUBIC)
    return result


def composite_final(cfg, canvas_size=(CANVAS_W, CANVAS_H)):
    """
    Composite background + all overlays into one RGBA image.
    canvas_size: output resolution (default 4K so it looks sharp everywhere)
    """
    W, H = canvas_size
    # Transparent if overlays-only, solid dark if background image is present
    # This lets overlays work on any Explorer theme when no bg is set
    has_bg = bool(cfg.get("image_path", "") and os.path.exists(cfg.get("image_path", "")))
    canvas_color = (10, 10, 16, 255) if has_bg else (0, 0, 0, 0)
    canvas = Image.new("RGBA", (W, H), canvas_color)

    # ── Background ────────────────────────────────────────────────────────────
    bg_path = cfg.get("image_path", "")
    if bg_path and os.path.exists(bg_path):
        bg = process_layer(
            bg_path,
            cfg.get("brightness", 1.0),
            cfg.get("blur", 0),
            cfg.get("opacity", 255),
            contrast = cfg.get("contrast", 1.0),
        )
        pos = cfg.get("pos_type", 6)

        if pos == 6:  # Zoom & Fill
            ratio = max(W / bg.width, H / bg.height)
            new_w, new_h = int(bg.width * ratio), int(bg.height * ratio)
            bg = bg.resize((new_w, new_h), Image.LANCZOS)
            x, y = (W - new_w) // 2, (H - new_h) // 2
        elif pos == 5:  # Stretch
            bg = bg.resize((W, H), Image.LANCZOS)
            x, y = 0, 0
        elif pos == 4:  # Center
            x, y = (W - bg.width) // 2, (H - bg.height) // 2
        elif pos == 0:  x, y = 0, 0                          # Top Left
        elif pos == 1:  x, y = W - bg.width, 0               # Top Right
        elif pos == 2:  x, y = 0, H - bg.height              # Bottom Left
        elif pos == 3:  x, y = W - bg.width, H - bg.height   # Bottom Right
        else:           x, y = 0, 0

        canvas.paste(bg, (x, y), bg)

    # ── Overlays ──────────────────────────────────────────────────────────────
    for ov in cfg.get("overlays", []):
        ov_path = ov.get("path", "")
        if not ov_path or not os.path.exists(ov_path):
            continue

        ov_img = process_layer(
            ov_path,
            ov.get("brightness", 1.0),
            ov.get("blur", 0),
            ov.get("opacity", 255),
            contrast = ov.get("contrast", 1.0),
            flip_h   = ov.get("flip_h", False),
            flip_v   = ov.get("flip_v", False),
            rotation = ov.get("rotation", 0),
        )

        # Scale based on % of canvas height
        scale_pct = ov.get("scale", 30) / 100.0
        target_h  = int(H * scale_pct)
        ratio     = target_h / ov_img.height if ov_img.height else 1
        target_w  = int(ov_img.width * ratio)
        ov_img    = ov_img.resize((target_w, target_h), Image.LANCZOS)

        pad_x     = ov.get("offset_x", 20)
        pad_y     = ov.get("offset_y", 20)
        pos       = ov.get("position", "br")
        custom_x  = ov.get("custom_x", -1)
        custom_y  = ov.get("custom_y", -1)

        cx = (W - target_w) // 2
        cy = (H - target_h) // 2

        # Custom X/Y position (0-100% of canvas) overrides anchor if set
        if custom_x >= 0 and custom_y >= 0:
            x = int(custom_x / 100 * (W - target_w))
            y = int(custom_y / 100 * (H - target_h))
        else:
            if   pos == "tl": x, y = pad_x,                pad_y
            elif pos == "tm": x, y = cx,                    pad_y
            elif pos == "tr": x, y = W-target_w-pad_x,     pad_y
            elif pos == "ml": x, y = pad_x,                cy
            elif pos == "cc": x, y = cx,                    cy
            elif pos == "mr": x, y = W-target_w-pad_x,     cy
            elif pos == "bl": x, y = pad_x,                H-target_h-pad_y
            elif pos == "bm": x, y = cx,                    H-target_h-pad_y
            else:             x, y = W-target_w-pad_x,     H-target_h-pad_y  # br

        canvas.paste(ov_img, (x, y), ov_img)

    return canvas


def to_jpeg_b64(img, max_size=(900, 560)):
    """Downscale for preview and return base64 JPEG. Uses dark bg only for preview."""
    preview = img.copy()
    preview.thumbnail(max_size, Image.LANCZOS)
    # Dark bg for preview only — actual PNG saved is transparent
    bg = Image.new("RGBA", preview.size, (13, 13, 20, 255))
    bg.paste(preview, (0, 0), preview)
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def save_final_image(cfg, image_dir):
    """Composite and save the final PNG into the explorerTool image folder."""
    os.makedirs(image_dir, exist_ok=True)
    img = composite_final(cfg)
    out = os.path.join(image_dir, "bg_custom.png")
    img.save(out, "PNG")  # transparent canvas preserved — Explorer theme shows through
    return out


def write_ini(ini_path, pos_type, image_folder, folder_ext=False):
    open(ini_path, "w").write(f"""[load]
folderExt={str(folder_ext).lower()}
noerror=false
[image]
random=false
custom=false
posType={pos_type}
imgAlpha=255
folder={image_folder}
""")

def register_dll(dll_path):
    return subprocess.run(["regsvr32", "/s", dll_path], capture_output=True).returncode == 0

def unregister_dll(dll_path):
    return subprocess.run(["regsvr32", "/s", "/u", dll_path], capture_output=True).returncode == 0

def restart_explorer():
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], capture_output=True)
    subprocess.Popen(["explorer.exe"])

def is_admin():
    try:
        import ctypes; return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except: return False

def get_desktop_wallpaper():
    import shutil
    temp_dir = os.path.join(SCRIPT_DIR, ".wallpaper_cache")
    os.makedirs(temp_dir, exist_ok=True)
    out_path = os.path.join(temp_dir, "current_wallpaper.jpg")

    # Method 1: TranscodedWallpaper (regular/custom wallpaper)
    transcoded = os.path.expandvars(r"%AppData%\Microsoft\Windows\Themes\TranscodedWallpaper")
    if os.path.exists(transcoded):
        try:
            img = Image.open(transcoded)
            if img.width >= 800 and img.height >= 600:
                img.convert("RGB").save(out_path, "JPEG", quality=95)
                return out_path
        except: pass

    # Method 2: Spotlight assets (largest landscape image)
    spotlight_dir = os.path.expandvars(r"%LocalAppData%\Packages\Microsoft.Windows.ContentDeliveryManager_cw5n1h2txyewy\LocalState\Assets")
    if os.path.exists(spotlight_dir):
        candidates = []
        for f in os.listdir(spotlight_dir):
            fp = os.path.join(spotlight_dir, f)
            try:
                sz = os.path.getsize(fp)
                if sz > 100_000:
                    candidates.append((sz, fp))
            except: pass
        candidates.sort(reverse=True)
        for _, fp in candidates[:5]:
            try:
                img = Image.open(fp)
                if img.width >= 1280 and img.height >= 720:
                    img.convert("RGB").save(out_path, "JPEG", quality=95)
                    return out_path
            except: pass

    return None


def pick_file(title, filetypes):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    path = filedialog.askopenfilename(title=title, filetypes=filetypes)
    root.destroy()
    return path or ""

# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Explorer Background Tool</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --bg:#0d0d14; --card:#13131f; --border:#1e1e30;
  --acc:#b48ef7; --ok:#7ee8a2; --err:#f87272; --blue:#7eb8f8;
  --fg:#e2e0f0; --muted:#5a5870; --slider:#2a2a40;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Syne',sans-serif;background:var(--bg);color:var(--fg);min-height:100vh;padding:28px 20px;}
.wrap{max-width:1100px;margin:0 auto;}
header{display:flex;align-items:center;gap:14px;margin-bottom:28px;}
h1{font-size:24px;font-weight:800;letter-spacing:-.5px;}
h1 span{color:var(--acc);}
.badge{margin-left:auto;font-family:'DM Mono',monospace;font-size:11px;padding:5px 12px;border-radius:99px;border:1px solid;}
.badge.ok{border-color:var(--ok);color:var(--ok);}
.badge.err{border-color:var(--err);color:var(--err);}

/* Layout */
.main-grid{display:grid;grid-template-columns:1fr 360px;gap:18px;}
.left{display:flex;flex-direction:column;gap:18px;}
.right{display:flex;flex-direction:column;gap:18px;}

/* Card */
.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px;}
.card-title{font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:14px;}

/* Preview */
#preview{width:100%;aspect-ratio:16/9;border-radius:10px;background:#080810;border:1px solid var(--border);display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:13px;overflow:hidden;}
#preview img{width:100%;height:100%;object-fit:cover;border-radius:10px;}

/* File row */
.file-row{display:flex;gap:8px;align-items:center;}
.fpath{flex:1;background:#0d0d18;border:1px solid var(--border);border-radius:8px;padding:8px 12px;font-family:'DM Mono',monospace;font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}

/* Buttons */
.btn{padding:8px 16px;border-radius:8px;border:none;font-family:'Syne',sans-serif;font-weight:700;font-size:12px;cursor:pointer;transition:all .15s;white-space:nowrap;}
.btn-acc{background:var(--acc);color:#0d0d14;}
.btn-dim{background:var(--border);color:var(--fg);}
.btn-ok{background:var(--ok);color:#0d0d14;}
.btn-err{background:var(--err);color:#0d0d14;}
.btn-blue{background:var(--blue);color:#0d0d14;}
.btn-ghost{background:transparent;color:var(--muted);border:1px solid var(--border);}
.btn:hover{filter:brightness(1.15);transform:translateY(-1px);}
.btn:active{transform:translateY(0);filter:brightness(.95);}

/* Sliders */
.sl-row{margin-bottom:14px;}
.sl-hdr{display:flex;justify-content:space-between;margin-bottom:6px;}
.sl-lbl{font-size:12px;font-weight:600;}
.sl-val{font-family:'DM Mono',monospace;font-size:11px;color:var(--acc);}
input[type=range]{-webkit-appearance:none;width:100%;height:4px;background:var(--slider);border-radius:2px;outline:none;}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;border-radius:50%;background:var(--acc);cursor:pointer;}

/* Position grid */
.pos-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;}
.pos-btn{padding:7px 4px;border-radius:7px;border:1px solid var(--border);background:#0d0d18;color:var(--muted);font-family:'Syne',sans-serif;font-size:10px;font-weight:600;cursor:pointer;transition:all .15s;text-align:center;}
.pos-btn:hover{border-color:var(--acc);color:var(--acc);}
.pos-btn.active{border-color:var(--acc);background:rgba(180,142,247,.12);color:var(--acc);}

/* Overlays */
.overlay-card{background:#0d0d18;border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:10px;}
.ov-header{display:flex;align-items:center;gap:8px;margin-bottom:12px;}
.ov-title{font-size:11px;font-weight:700;color:var(--acc);flex:1;}
.ov-pos-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:5px;margin-bottom:12px;}
.ov-pos-btn{padding:6px;border-radius:6px;border:1px solid var(--border);background:#13131f;color:var(--muted);font-size:10px;font-weight:600;cursor:pointer;transition:all .15s;text-align:center;}
.ov-pos-btn:hover{border-color:var(--acc);color:var(--acc);}
.ov-pos-btn.active{border-color:var(--acc);background:rgba(180,142,247,.12);color:var(--acc);}

hr{border:none;border-top:1px solid var(--border);margin:14px 0;}
.adv-toggle{width:100%;background:none;border:1px dashed var(--border);border-radius:6px;color:var(--muted);font-family:'Syne',sans-serif;font-size:10px;font-weight:700;padding:6px;cursor:pointer;text-align:center;letter-spacing:1px;transition:all .2s;margin-top:10px;}
.adv-toggle:hover{border-color:var(--acc);color:var(--acc);}
.adv-body{display:none;margin-top:10px;padding-top:10px;border-top:1px solid var(--border);}
.adv-body.open{display:block;}
.flip-row{display:flex;gap:8px;margin-bottom:14px;}
.flip-btn{flex:1;padding:7px;border-radius:7px;border:1px solid var(--border);background:#0d0d18;color:var(--muted);font-family:'Syne',sans-serif;font-size:11px;font-weight:700;cursor:pointer;transition:all .15s;text-align:center;}
.flip-btn:hover{border-color:var(--acc);color:var(--acc);}
.flip-btn.active{border-color:var(--acc);background:rgba(180,142,247,.12);color:var(--acc);}
.hint{font-size:11px;color:var(--muted);line-height:1.6;margin-top:5px;}

/* Toast */
#toast{position:fixed;bottom:28px;left:50%;transform:translateX(-50%);padding:10px 22px;border-radius:99px;font-size:13px;font-weight:600;pointer-events:none;opacity:0;transition:opacity .3s;z-index:999;}
#toast.show{opacity:1;}
#toast.ok{background:var(--ok);color:#0d0d14;}
#toast.err{background:var(--err);color:#fff;}
#toast.info{background:var(--acc);color:#0d0d14;}
.spin{display:inline-block;animation:spin .8s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}

/* Add overlay btn */
.add-ov-btn{width:100%;padding:10px;border-radius:8px;border:1px dashed var(--border);background:transparent;color:var(--muted);font-family:'Syne',sans-serif;font-size:12px;font-weight:700;cursor:pointer;transition:all .2s;}
.add-ov-btn:hover{border-color:var(--acc);color:var(--acc);}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div style="font-size:26px;">🖼️</div>
    <h1>Explorer <span>Background</span> Tool</h1>
    <div class="badge" id="adminBadge">checking...</div>
  </header>

  <div class="main-grid">
    <!-- LEFT -->
    <div class="left">

      <!-- Preview -->
      <div class="card">
        <div class="card-title">Live Preview (all layers)</div>
        <div id="preview"><span class="spin" style="display:none" id="previewSpinner">⟳</span><span id="previewEmpty">No image selected</span></div>
      </div>

      <!-- Background -->
      <div class="card">
        <div class="card-title">🌄 Background Layer</div>
        <div class="file-row">
          <div class="fpath" id="bgPathLabel">No image selected</div>
          <button class="btn btn-acc" onclick="pickBg()">Browse</button>
          <button class="btn btn-dim" onclick="useWallpaper()" title="Use current desktop wallpaper">🖥️ Wallpaper</button>
          <button class="btn btn-err" onclick="clearBg()" title="Remove background image, keep overlays" style="font-size:11px;padding:8px 12px;">🗑 Clear</button>
          <span id="wallpaperSyncBadge" style="display:none;font-size:10px;font-family:'DM Mono',monospace;color:var(--ok);border:1px solid var(--ok);border-radius:99px;padding:3px 8px;white-space:nowrap;">⟳ auto-sync</span>
        </div>
        <p class="hint">PNG, JPG, WEBP, BMP</p>
        <label style="display:flex;align-items:center;gap:8px;margin-top:10px;cursor:pointer;font-size:12px;font-weight:600;color:var(--fg);">
          <input type="checkbox" id="folderExt" onchange="schedulePreview()"
            style="width:15px;height:15px;accent-color:var(--acc);cursor:pointer;">
          Also apply to Windows file picker dialogs
        </label>
        <hr>
        <div class="card-title">Background Adjustments</div>
        <div class="sl-row">
          <div class="sl-hdr"><span class="sl-lbl">✨ Brightness</span><span class="sl-val" id="bgBrightVal">1.0×</span></div>
          <input type="range" id="bgBrightness" min="10" max="200" value="100" oninput="updSlider('bgBrightness','bgBrightVal',v=>(v/100).toFixed(1)+'×');schedulePreview()">
        </div>
        <div class="sl-row">
          <div class="sl-hdr"><span class="sl-lbl">🎨 Contrast</span><span class="sl-val" id="bgContrastVal">1.0×</span></div>
          <input type="range" id="bgContrast" min="10" max="200" value="100" oninput="updSlider('bgContrast','bgContrastVal',v=>(v/100).toFixed(1)+'×');schedulePreview()">
        </div>
        <div class="sl-row">
          <div class="sl-hdr"><span class="sl-lbl">🌫️ Blur / Haze</span><span class="sl-val" id="bgBlurVal">0px</span></div>
          <input type="range" id="bgBlur" min="0" max="20" value="0" oninput="updSlider('bgBlur','bgBlurVal',v=>v+'px');schedulePreview()">
        </div>
        <div class="sl-row">
          <div class="sl-hdr"><span class="sl-lbl">💧 Opacity</span><span class="sl-val" id="bgOpacVal">255</span></div>
          <input type="range" id="bgOpacity" min="0" max="255" value="255" oninput="updSlider('bgOpacity','bgOpacVal',v=>v);schedulePreview()">
        </div>
      </div>

      <!-- Overlays list -->
      <div class="card">
        <div class="card-title">🎨 Foreground Overlays <span style="color:var(--muted);font-size:10px;font-weight:400;text-transform:none;letter-spacing:0;">(optional — add as many as you want)</span></div>
        <div id="overlayList"></div>
        <button class="add-ov-btn" onclick="addOverlay()">＋ Add Foreground Image</button>
      </div>

    </div>

    <!-- RIGHT -->
    <div class="right">

      <!-- BG Position -->
      <div class="card">
        <div class="card-title">Background Position</div>
        <div class="pos-grid" id="bgPosGrid">
          <button class="pos-btn" onclick="setBgPos(0)">↖ Top Left</button>
          <button class="pos-btn" onclick="setBgPos(1)">↗ Top Right</button>
          <button class="pos-btn" onclick="setBgPos(2)">↙ Bot Left</button>
          <button class="pos-btn" onclick="setBgPos(3)">↘ Bot Right</button>
          <button class="pos-btn" onclick="setBgPos(4)">⊙ Center</button>
          <button class="pos-btn" onclick="setBgPos(5)">⤢ Stretch</button>
          <button class="pos-btn active" style="grid-column:span 3" onclick="setBgPos(6)">⊞ Zoom & Fill ← recommended</button>
        </div>
      </div>

      <!-- DLL -->
      <div class="card">
        <div class="card-title">ExplorerTool DLL</div>
        <p class="hint">Select ExplorerBgTool.dll</p>
        <div class="file-row" style="margin-top:8px;">
          <div class="fpath" id="dllPathLabel">Not selected</div>
          <button class="btn btn-dim" onclick="pickDll()">Browse</button>
        </div>
      </div>

      <!-- Actions -->
      <div class="card">
        <div class="card-title">Actions</div>
        <div style="display:flex;flex-direction:column;gap:8px;">
          <button class="btn btn-ok" style="width:100%;padding:13px;font-size:13px;" onclick="applyBg()">✅ Apply to Explorer</button>
          <button class="btn btn-blue" style="width:100%" onclick="restartExp()">🔄 Restart Explorer</button>
          <button class="btn btn-err" style="width:100%" onclick="uninstall()">❌ Uninstall Background</button>
        </div>
        <p class="hint" style="margin-top:10px;">After applying, click Restart Explorer or reopen File Explorer windows.</p>
      </div>

    </div>
  </div>
</div>
<div id="toast"></div>

<script>
let cfg = {};
let previewTimer = null;
// overlays: { id, path, position, scale, brightness, blur, opacity }
let overlays = [];
let bgPos = 6;

async function api(ep, params={}) {
  // Use POST with JSON body to avoid URL encoding issues with file paths containing spaces
  const r = await fetch(`/api/${ep}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(params)
  });
  return r.json();
}

async function init() {
  cfg = await api('config');
  // admin badge
  const b = document.getElementById('adminBadge');
  b.textContent = cfg.is_admin ? '✓ Administrator' : '⚠ Not Admin';
  b.className = 'badge ' + (cfg.is_admin ? 'ok' : 'err');
  // restore bg
  setSlider('bgBrightness','bgBrightVal', Math.round(cfg.brightness*100), v=>(v/100).toFixed(1)+'×');
  setSlider('bgContrast','bgContrastVal', Math.round((cfg.contrast||1.0)*100), v=>(v/100).toFixed(1)+'×');
  setSlider('bgBlur','bgBlurVal', cfg.blur, v=>v+'px');
  setSlider('bgOpacity','bgOpacVal', cfg.opacity, v=>v);
  if (cfg.image_path) document.getElementById('bgPathLabel').textContent = fname(cfg.image_path);
  if (cfg.wallpaper_mode) document.getElementById('wallpaperSyncBadge').style.display = 'inline';
  document.getElementById('folderExt').checked = cfg.folder_ext || false;
  if (cfg.dll_path)   document.getElementById('dllPathLabel').textContent = fname(cfg.dll_path);
  setBgPos(cfg.pos_type ?? 6);
  // restore overlays
  overlays = (cfg.overlays || []).map(ov => ({...ov}));
  overlays.forEach(ov => renderOverlay(ov));
  // trigger preview only if we have something to show
  if (cfg.image_path || overlays.some(o => o.path)) schedulePreview();
}

function fname(p) { return p.split(/[\\/]/).pop(); }

function setSlider(id, valId, val, fmt) {
  document.getElementById(id).value = val;
  document.getElementById(valId).textContent = fmt(val);
}
function updSlider(id, valId, fmt) {
  const v = document.getElementById(id).value;
  document.getElementById(valId).textContent = fmt(v);
}

function setBgPos(n) {
  bgPos = n;
  document.querySelectorAll('#bgPosGrid .pos-btn').forEach((b,i) => b.classList.toggle('active', i===n));
}

// ── Preview ───────────────────────────────────────────────────────────────────
function schedulePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(doPreview, 400);
}

function clearPreview() {
  const prev = document.getElementById('preview');
  prev.innerHTML = '<span id="previewEmpty" style="color:var(--muted);font-size:13px;">No image selected</span>';
}

async function doPreview() {
  if (!cfg.image_path && overlays.filter(o=>o.path).length === 0) return;
  const prev = document.getElementById('preview');
  const params = buildParams();
  console.log('[preview] requesting with image_path:', cfg.image_path);
  const res = await api('preview', params);
  console.log('[preview] response img length:', res.img ? res.img.length : 'null', 'error:', res.error);
  if (res.img) {
    const img = new Image();
    img.onload = () => { prev.innerHTML = ''; prev.appendChild(img); };
    img.onerror = (e) => console.error('[preview] img failed to load', e);
    img.style.cssText = 'width:100%;height:100%;object-fit:cover;border-radius:10px;';
    img.src = 'data:image/jpeg;base64,' + res.img;
  }
}

function buildParams() {
  return {
    image_path:  cfg.image_path || '',
    brightness:  document.getElementById('bgBrightness').value / 100,
    contrast:    document.getElementById('bgContrast').value / 100,
    blur:        document.getElementById('bgBlur').value,
    opacity:     document.getElementById('bgOpacity').value,
    pos_type:    bgPos,
    overlays:    JSON.stringify(overlays),
    folder_ext:  document.getElementById('folderExt').checked,
  };
}

// ── Background pick ───────────────────────────────────────────────────────────
async function clearBg() {
  cfg.image_path = '';
  document.getElementById('bgPathLabel').textContent = 'No image selected';
  document.getElementById('wallpaperSyncBadge').style.display = 'none';
  await api('clear_bg');
  // Force immediate preview with empty image_path
  const prev = document.getElementById('preview');
  if (overlays.filter(o => o.path).length === 0) {
    clearPreview();
  } else {
    doPreview();
  }
  toast('Background cleared! Overlays preserved.', 'info');
}

async function useWallpaper() {
  toast('Grabbing wallpaper...', 'info');
  const r = await api('use_wallpaper');
  if (r.ok) {
    cfg.image_path = r.path;
    document.getElementById('bgPathLabel').textContent = 'current_wallpaper.jpg';
    document.getElementById('wallpaperSyncBadge').style.display = 'inline';
    schedulePreview();
    toast('Desktop wallpaper loaded! Auto-sync ON 🔄', 'ok');
  } else {
    toast(r.msg || 'Could not get wallpaper!', 'err');
  }
}

async function pickBg() {
  const r = await api('pick_image');
  if (r.path) {
    cfg.image_path = r.path;
    document.getElementById('bgPathLabel').textContent = fname(r.path);
    document.getElementById('wallpaperSyncBadge').style.display = 'none';
    schedulePreview();
    toast('Background image selected!', 'info');
  }
}

async function pickDll() {
  const r = await api('pick_dll');
  if (r.path) {
    cfg.dll_path = r.path;
    document.getElementById('dllPathLabel').textContent = fname(r.path);
    toast('DLL selected!', 'info');
  }
}

// ── Overlays ──────────────────────────────────────────────────────────────────
function addOverlay() {
  const ov = {
    id: 'ov_' + Date.now(),
    path: '', position: 'br',
    scale: 30, brightness: 1.0, blur: 0, opacity: 255,
    offset_x: 20, offset_y: 20,
  };
  overlays.push(ov);
  renderOverlay(ov);
}

function renderOverlay(ov) {
  const list = document.getElementById('overlayList');
  const div  = document.createElement('div');
  div.className = 'overlay-card';
  div.id = 'ov_card_' + ov.id;

  const posLabels = [
    {k:'tl',v:'↖ TL'}, {k:'tm',v:'↑ Top'}, {k:'tr',v:'↗ TR'},
    {k:'ml',v:'← Left'},{k:'cc',v:'⊙ Center'},{k:'mr',v:'→ Right'},
    {k:'bl',v:'↙ BL'}, {k:'bm',v:'↓ Bot'}, {k:'br',v:'↘ BR'},
  ];

  // Compute initial XY slider values from position anchor
  const posToXY = {
    tl:[0,0], tm:[50,0], tr:[100,0],
    ml:[0,50], cc:[50,50], mr:[100,50],
    bl:[0,100], bm:[50,100], br:[100,100]
  };
  const initXY = (ov.custom_x >= 0 && ov.custom_y >= 0)
    ? [ov.custom_x, ov.custom_y]
    : (posToXY[ov.position] || [100,100]);

  div.innerHTML = `
    <div class="ov-header">
      <span class="ov-title">🎨 Overlay ${overlays.indexOf(ov)+1}</span>
      <span class="fpath" id="ovPath_${ov.id}" style="flex:1;max-width:140px;">${ov.path ? fname(ov.path) : 'No image'}</span>
      <button class="btn btn-acc" style="font-size:10px;padding:5px 10px;" onclick="pickOverlayImg('${ov.id}')">Browse</button>
      <button class="btn btn-err" style="font-size:10px;padding:5px 10px;margin-left:4px;" onclick="removeOverlay('${ov.id}')">✕</button>
    </div>

    <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);margin-bottom:6px;">Position</div>
    <div class="ov-pos-grid" id="ovPosGrid_${ov.id}" style="grid-template-columns:repeat(3,1fr);">
      ${posLabels.map(({k,v})=>`
        <button class="ov-pos-btn ${ov.position===k && (ov.custom_x<0||ov.custom_y<0) ?'active':''}" onclick="setOvPos('${ov.id}','${k}')">${v}</button>
      `).join('')}
    </div>

    <div class="sl-row">
      <div class="sl-hdr"><span class="sl-lbl">📐 Size</span><span class="sl-val" id="ovScaleVal_${ov.id}">${ov.scale}%</span></div>
      <input type="range" id="ovScale_${ov.id}" min="5" max="80" value="${ov.scale}"
        oninput="updOvSlider('${ov.id}','scale','ovScale','ovScaleVal',v=>v+'%')"
        onchange="schedulePreview()">
    </div>
    <div class="sl-row">
      <div class="sl-hdr"><span class="sl-lbl">✨ Brightness</span><span class="sl-val" id="ovBrightVal_${ov.id}">${ov.brightness.toFixed(1)}×</span></div>
      <input type="range" id="ovBright_${ov.id}" min="10" max="200" value="${Math.round(ov.brightness*100)}"
        oninput="updOvSlider('${ov.id}','brightness','ovBright','ovBrightVal',v=>(v/100).toFixed(1)+'×',v=>v/100)"
        onchange="schedulePreview()">
    </div>
    <div class="sl-row">
      <div class="sl-hdr"><span class="sl-lbl">🌫️ Blur</span><span class="sl-val" id="ovBlurVal_${ov.id}">${ov.blur}px</span></div>
      <input type="range" id="ovBlur_${ov.id}" min="0" max="20" value="${ov.blur}"
        oninput="updOvSlider('${ov.id}','blur','ovBlur','ovBlurVal',v=>v+'px')"
        onchange="schedulePreview()">
    </div>
    <div class="sl-row">
      <div class="sl-hdr"><span class="sl-lbl">💧 Opacity</span><span class="sl-val" id="ovOpacVal_${ov.id}">${ov.opacity}</span></div>
      <input type="range" id="ovOpac_${ov.id}" min="0" max="255" value="${ov.opacity}"
        oninput="updOvSlider('${ov.id}','opacity','ovOpac','ovOpacVal',v=>v)"
        onchange="schedulePreview()">
    </div>

    <!-- ── Advanced Section ──────────────────────────────────────── -->
    <button class="adv-toggle" onclick="toggleAdv('${ov.id}')">▸ ADVANCED</button>
    <div class="adv-body" id="advBody_${ov.id}">

      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);margin-bottom:8px;">Custom Position</div>
      <div class="sl-row">
        <div class="sl-hdr"><span class="sl-lbl">↔️ Left → Right</span><span class="sl-val" id="ovXVal_${ov.id}">${initXY[0]}%</span></div>
        <input type="range" id="ovX_${ov.id}" min="0" max="100" value="${initXY[0]}"
          oninput="updOvXY('${ov.id}')"
          onchange="schedulePreview()">
      </div>
      <div class="sl-row">
        <div class="sl-hdr"><span class="sl-lbl">↕️ Top → Bottom</span><span class="sl-val" id="ovYVal_${ov.id}">${initXY[1]}%</span></div>
        <input type="range" id="ovY_${ov.id}" min="0" max="100" value="${initXY[1]}"
          oninput="updOvXY('${ov.id}')"
          onchange="schedulePreview()">
      </div>

      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);margin-bottom:8px;margin-top:4px;">Effects</div>
      <div class="sl-row">
        <div class="sl-hdr"><span class="sl-lbl">🎨 Contrast</span><span class="sl-val" id="ovContrastVal_${ov.id}">${(ov.contrast||1.0).toFixed(1)}×</span></div>
        <input type="range" id="ovContrast_${ov.id}" min="10" max="200" value="${Math.round((ov.contrast||1.0)*100)}"
          oninput="updOvSlider('${ov.id}','contrast','ovContrast','ovContrastVal',v=>(v/100).toFixed(1)+'×',v=>v/100)"
          onchange="schedulePreview()">
      </div>

      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);margin-bottom:8px;margin-top:4px;">Transform</div>
      <div class="flip-row">
        <button class="flip-btn ${ov.flip_h?'active':''}" id="flipH_${ov.id}" onclick="toggleFlip('${ov.id}','flip_h','flipH_${ov.id}')">↔ Flip H</button>
        <button class="flip-btn ${ov.flip_v?'active':''}" id="flipV_${ov.id}" onclick="toggleFlip('${ov.id}','flip_v','flipV_${ov.id}')">↕ Flip V</button>
      </div>
      <div class="sl-row">
        <div class="sl-hdr"><span class="sl-lbl">🔄 Rotation</span><span class="sl-val" id="ovRotVal_${ov.id}">${ov.rotation||0}°</span></div>
        <input type="range" id="ovRot_${ov.id}" min="0" max="359" value="${ov.rotation||0}"
          oninput="updOvSlider('${ov.id}','rotation','ovRot','ovRotVal',v=>v+'°')"
          onchange="schedulePreview()">
      </div>

    </div>
  `;
  list.appendChild(div);
}

function toggleAdv(id) {
  const body = document.getElementById('advBody_' + id);
  const btn  = body.previousElementSibling;
  body.classList.toggle('open');
  btn.textContent = body.classList.contains('open') ? '▾ ADVANCED' : '▸ ADVANCED';
}

function updOvXY(id) {
  const x = parseFloat(document.getElementById('ovX_' + id).value);
  const y = parseFloat(document.getElementById('ovY_' + id).value);
  document.getElementById('ovXVal_' + id).textContent = x + '%';
  document.getElementById('ovYVal_' + id).textContent = y + '%';
  const ov = overlays.find(o => o.id === id);
  if (ov) { ov.custom_x = x; ov.custom_y = y; ov.position = 'custom'; }
  // Deactivate all 9 position buttons
  document.querySelectorAll('#ovPosGrid_' + id + ' .ov-pos-btn').forEach(b => b.classList.remove('active'));
}

function toggleFlip(id, field, btnId) {
  const ov = overlays.find(o => o.id === id);
  if (!ov) return;
  ov[field] = !ov[field];
  document.getElementById(btnId).classList.toggle('active', ov[field]);
  schedulePreview();
}

function updOvSlider(id, field, sliderPrefix, valPrefix, fmt, transform) {
  const raw = document.getElementById(`${sliderPrefix}_${id}`).value;
  document.getElementById(`${valPrefix}_${id}`).textContent = fmt(raw);
  const ov = overlays.find(o => o.id === id);
  if (ov) ov[field] = transform ? transform(parseFloat(raw)) : parseFloat(raw);
}

function setOvPos(id, pos) {
  const ov = overlays.find(o => o.id === id);
  if (ov) { ov.position = pos; ov.custom_x = -1; ov.custom_y = -1; }
  const keyMap = {tl:'TL',tm:'Top',tr:'TR',ml:'Left',cc:'Center',mr:'Right',bl:'BL',bm:'Bot',br:'BR'};
  document.querySelectorAll(`#ovPosGrid_${id} .ov-pos-btn`).forEach(b => {
    b.classList.toggle('active', b.textContent.includes(keyMap[pos]));
  });
  // Snap X/Y sliders to match chosen position
  const posToXY = {tl:[0,0],tm:[50,0],tr:[100,0],ml:[0,50],cc:[50,50],mr:[100,50],bl:[0,100],bm:[50,100],br:[100,100]};
  const xy = posToXY[pos] || [100,100];
  const xEl = document.getElementById('ovX_'+id);
  const yEl = document.getElementById('ovY_'+id);
  if (xEl) { xEl.value = xy[0]; document.getElementById('ovXVal_'+id).textContent = xy[0]+'%'; }
  if (yEl) { yEl.value = xy[1]; document.getElementById('ovYVal_'+id).textContent = xy[1]+'%'; }
  schedulePreview();
}

async function pickOverlayImg(id) {
  const r = await api('pick_overlay_image');  // separate endpoint - does NOT touch background path
  if (r.path) {
    const ov = overlays.find(o => o.id === id);
    if (ov) ov.path = r.path;
    document.getElementById(`ovPath_${id}`).textContent = fname(r.path);
    schedulePreview();
    toast('Overlay image selected!', 'info');
  }
}

function removeOverlay(id) {
  overlays = overlays.filter(o => o.id !== id);
  const card = document.getElementById('ov_card_' + id);
  if (card) card.remove();
  // re-number titles
  document.querySelectorAll('.ov-title').forEach((t,i) => t.textContent = `🎨 Overlay ${i+1}`);
  // If nothing left to show, clear preview immediately
  const hasOverlays = overlays.filter(o => o.path).length > 0;
  const hasBg = cfg.image_path && cfg.image_path.length > 0;
  if (!hasOverlays && !hasBg) {
    clearPreview();
  } else {
    doPreview();
  }
}

// ── Apply / Actions ───────────────────────────────────────────────────────────
async function applyBg() {
  const params = buildParams();
  params.dll_path = cfg.dll_path || '';
  const r = await api('apply', params);
  toast(r.msg, r.ok ? 'ok' : 'err');
}

async function restartExp() {
  if (!confirm('This will briefly close all Explorer windows. Continue?')) return;
  await api('restart_explorer');
  toast('Explorer restarted!', 'info');
}

async function uninstall() {
  if (!confirm('Remove background from Explorer?')) return;
  const r = await api('uninstall');
  toast(r.msg, r.ok ? 'ok' : 'err');
}

function toast(msg, type='info') {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = `show ${type}`;
  setTimeout(() => t.className = '', 3500);
}

init();
</script>
</body>
</html>"""

# ── HTTP Handler ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    cfg = load_config()
    def log_message(self, *a): pass

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self._handle()

    def do_GET(self):
        self._handle()

    def _handle(self):
        parsed = urlparse(self.path)
        # Parse params from JSON body (POST) or query string (GET)
        params = {}
        if self.command == 'POST':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)
                params = json.loads(body)
            except: pass
        else:
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if parsed.path == "/":
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body); return

        if parsed.path == "/api/config":
            self.send_json({**self.cfg, "is_admin": is_admin()})

        elif parsed.path == "/api/preview":
            img_path = self.cfg.get("image_path", "")
            overlays_raw = []
            try:
                overlays_raw = json.loads(params.get("overlays", "[]"))
            except: pass

            # Nothing to show
            if not img_path and not overlays_raw:
                self.send_json({"img": None}); return

            # Path set but file missing
            if img_path and not os.path.exists(img_path):
                self.send_json({"img": None, "error": "image file not found"}); return

            try:
                cfg_snap = {
                    "image_path": img_path,
                    "brightness": float(params.get("brightness", 1.0)),
                    "contrast":   float(params.get("contrast", 1.0)),
                    "blur":       int(params.get("blur", 0)),
                    "opacity":    int(params.get("opacity", 255)),
                    "pos_type":   int(params.get("pos_type", 6)),
                    "overlays":   overlays_raw,
                }
                img = composite_final(cfg_snap, canvas_size=(800, 450))
                b64 = to_jpeg_b64(img, max_size=(800, 450))
                self.send_json({"img": b64})
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json({"img": None, "error": str(e)})

        elif parsed.path == "/api/pick_image":
            path = pick_file("Pick image",
                [("Images", "*.png *.jpg *.jpeg *.bmp *.webp"), ("All", "*.*")])
            if path:
                self.cfg["image_path"] = path        # update in memory only
                self.cfg["wallpaper_mode"] = False   # stop auto-sync in memory
                stop_watcher()
                # NOT saving to config — only Apply does that
            self.send_json({"path": path})

        elif parsed.path == "/api/clear_bg":
            self.cfg["image_path"] = ""      # update in memory only
            self.cfg["wallpaper_mode"] = False
            stop_watcher()
            # NOT saving to config — only Apply does that
            self.send_json({"ok": True})

        elif parsed.path == "/api/use_wallpaper":
            path = get_desktop_wallpaper()
            if path:
                self.cfg["image_path"] = path     # update in memory only
                self.cfg["wallpaper_mode"] = True  # update in memory only
                # NOT saving to config — only Apply does that
                # Start watcher if not already running
                if not _watcher_thread or not _watcher_thread.is_alive():
                    start_watcher(self.cfg)
                self.send_json({"ok": True, "path": path})
            else:
                self.send_json({"ok": False, "msg": "Could not find desktop wallpaper!"})

        elif parsed.path == "/api/pick_overlay_image":
            # Separate from pick_image - does NOT update self.cfg["image_path"]
            path = pick_file("Pick overlay image",
                [("Images", "*.png *.jpg *.jpeg *.bmp *.webp"), ("All", "*.*")])
            self.send_json({"path": path})

        elif parsed.path == "/api/pick_dll":
            path = pick_file("Select ExplorerBgTool.dll",
                [("DLL", "*.dll"), ("All", "*.*")])
            if path:
                self.cfg["dll_path"] = path
                save_config(self.cfg)
            self.send_json({"path": path})

        elif parsed.path == "/api/apply":
            dll = params.get("dll_path") or self.cfg.get("dll_path", "")
            if not dll or not os.path.exists(dll):
                self.send_json({"ok": False, "msg": "DLL not selected!"}); return

            cfg_snap = self._params_to_cfg(params)
            # persist
            self.cfg.update({
                "image_path": cfg_snap["image_path"],
                "brightness": cfg_snap["brightness"],
                "contrast":   cfg_snap["contrast"],
                "blur":       cfg_snap["blur"],
                "opacity":    cfg_snap["opacity"],
                "pos_type":   cfg_snap["pos_type"],
                "overlays":   cfg_snap["overlays"],
                "folder_ext": cfg_snap["folder_ext"],
                "dll_path":   dll,
            })
            save_config(self.cfg)

            try:
                dll_dir   = os.path.dirname(dll)
                image_dir = os.path.join(dll_dir, "image")
                ini_path  = os.path.join(dll_dir, "config.ini")
                save_final_image(cfg_snap, image_dir)
                write_ini(ini_path, 6, image_dir, cfg_snap.get("folder_ext", False))  # always Zoom&Fill for the composited image
                ok = register_dll(dll)
                if ok:
                    self.send_json({"ok": True,  "msg": "Applied! Now restart Explorer."})
                else:
                    self.send_json({"ok": False, "msg": "regsvr32 failed — run as Admin?"})
            except PermissionError:
                self.send_json({"ok": False, "msg": "Permission denied — run as Administrator!"})
            except Exception as e:
                self.send_json({"ok": False, "msg": f"Error: {e}"})

        elif parsed.path == "/api/restart_explorer":
            restart_explorer()
            self.send_json({"msg": "Explorer restarted!"})

        elif parsed.path == "/api/uninstall":
            dll = self.cfg.get("dll_path", "")
            if not dll or not os.path.exists(dll):
                self.send_json({"ok": False, "msg": "DLL not selected!"}); return
            ok = unregister_dll(dll)
            self.send_json({"ok": ok,
                "msg": "Uninstalled! Restart Explorer." if ok else "Failed — run as Admin?"})

        else:
            self.send_response(404); self.end_headers()

    def _params_to_cfg(self, params):
        """Build a cfg dict from URL params for compositing."""
        overlays = []
        try:
            overlays = json.loads(params.get("overlays", "[]"))
        except: pass
        return {
            # Use path sent directly from browser (most up to date), fallback to saved config
            "image_path": params.get("image_path", self.cfg.get("image_path", "")),
            "brightness": float(params.get("brightness", 1.0)),
            "contrast":   float(params.get("contrast", 1.0)),
            "blur":       int(params.get("blur", 0)),
            "opacity":    int(params.get("opacity", 255)),
            "pos_type":   int(params.get("pos_type", 6)),
            "overlays":    overlays,
            "folder_ext":  params.get("folder_ext", False) in [True, "true", "True"],
        }


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"\n  Explorer Background Tool running at {url}")
    print(f"  Admin: {is_admin()}")
    print(f"  Press Ctrl+C to stop.\n")
    # Resume wallpaper watcher if it was active last session
    if Handler.cfg.get("wallpaper_mode"):
        print("[watcher] Resuming wallpaper auto-sync from last session...")
        start_watcher(Handler.cfg)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_watcher()
        print("\nStopped.")

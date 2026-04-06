"""
wallpaper_watcher.py
Standalone silent watcher — auto-applies desktop wallpaper to Explorer
when Windows Spotlight (or any wallpaper) changes.

Auto-started on login via Task Scheduler (set up by SETUP_AUTOSTART.bat).
Reads all settings from bg_config.json. No window, no browser.
"""

import os, sys, json, shutil, subprocess, time, threading
from PIL import Image, ImageEnhance, ImageFilter

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "bg_config.json")
CACHE_DIR   = os.path.join(SCRIPT_DIR, ".wallpaper_cache")
WALLPAPER_PATH = os.path.join(CACHE_DIR, "current_wallpaper.jpg")
CHECK_INTERVAL = 1800  # 30 minutes
CANVAS_W, CANVAS_H = 3840, 2160

# ── Logging to file (no window) ───────────────────────────────────────────────
LOG_FILE = os.path.join(SCRIPT_DIR, ".wallpaper_cache", "watcher.log")

def log(msg):
    os.makedirs(CACHE_DIR, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}\n"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except: pass

# ── Config ────────────────────────────────────────────────────────────────────
def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except: pass

# ── Wallpaper detection ───────────────────────────────────────────────────────
def get_transcoded_mtime():
    path = os.path.expandvars(r"%AppData%\Microsoft\Windows\Themes\TranscodedWallpaper")
    try:
        return os.path.getmtime(path)
    except:
        return None

def get_desktop_wallpaper():
    os.makedirs(CACHE_DIR, exist_ok=True)

    # Method 1: TranscodedWallpaper
    transcoded = os.path.expandvars(r"%AppData%\Microsoft\Windows\Themes\TranscodedWallpaper")
    if os.path.exists(transcoded):
        try:
            img = Image.open(transcoded)
            if img.width >= 800 and img.height >= 600:
                img.convert("RGB").save(WALLPAPER_PATH, "JPEG", quality=95)
                return WALLPAPER_PATH
        except: pass

    # Method 2: Spotlight assets
    spotlight_dir = os.path.expandvars(
        r"%LocalAppData%\Packages\Microsoft.Windows.ContentDeliveryManager_cw5n1h2txyewy\LocalState\Assets"
    )
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
                    img.convert("RGB").save(WALLPAPER_PATH, "JPEG", quality=95)
                    return WALLPAPER_PATH
            except: pass

    return None

# ── Image processing ──────────────────────────────────────────────────────────
def process_layer(src, brightness, blur, opacity, contrast=1.0,
                  flip_h=False, flip_v=False, rotation=0):
    img = Image.open(src).convert("RGBA")
    r, g, b, a = img.split()
    rgb = Image.merge("RGB", (r, g, b))
    rgb = ImageEnhance.Brightness(rgb).enhance(brightness)
    if contrast != 1.0:
        rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
    if blur > 0:
        rgb = rgb.filter(ImageFilter.GaussianBlur(radius=blur))
        a   = a.filter(ImageFilter.GaussianBlur(radius=blur * 0.5))
    a = a.point(lambda p: int(p * opacity / 255))
    r2, g2, b2 = rgb.split()
    result = Image.merge("RGBA", (r2, g2, b2, a))
    if flip_h: result = result.transpose(Image.FLIP_LEFT_RIGHT)
    if flip_v: result = result.transpose(Image.FLIP_TOP_BOTTOM)
    if rotation != 0: result = result.rotate(-rotation, expand=True, resample=Image.BICUBIC)
    return result

def composite_final(cfg, canvas_size=(CANVAS_W, CANVAS_H)):
    W, H = canvas_size
    has_bg = bool(cfg.get("image_path", "") and os.path.exists(cfg.get("image_path", "")))
    canvas_color = (10, 10, 16, 255) if has_bg else (0, 0, 0, 0)
    canvas = Image.new("RGBA", (W, H), canvas_color)

    # Background
    bg_path = cfg.get("image_path", "")
    if bg_path and os.path.exists(bg_path):
        bg = process_layer(bg_path, cfg.get("brightness", 1.0),
                           cfg.get("blur", 0), cfg.get("opacity", 255),
                           contrast=cfg.get("contrast", 1.0))
        pos = cfg.get("pos_type", 6)
        if pos == 6:
            ratio = max(W / bg.width, H / bg.height)
            new_w, new_h = int(bg.width * ratio), int(bg.height * ratio)
            bg = bg.resize((new_w, new_h), Image.LANCZOS)
            x, y = (W - new_w) // 2, (H - new_h) // 2
        elif pos == 5: bg = bg.resize((W, H), Image.LANCZOS); x, y = 0, 0
        elif pos == 4: x, y = (W - bg.width)//2, (H - bg.height)//2
        elif pos == 0: x, y = 0, 0
        elif pos == 1: x, y = W - bg.width, 0
        elif pos == 2: x, y = 0, H - bg.height
        elif pos == 3: x, y = W - bg.width, H - bg.height
        else: x, y = 0, 0
        canvas.paste(bg, (x, y), bg)

    # Overlays
    for ov in cfg.get("overlays", []):
        ov_path = ov.get("path", "")
        if not ov_path or not os.path.exists(ov_path): continue
        ov_img = process_layer(ov_path, ov.get("brightness", 1.0),
                               ov.get("blur", 0), ov.get("opacity", 255),
                               contrast=ov.get("contrast", 1.0),
                               flip_h=ov.get("flip_h", False),
                               flip_v=ov.get("flip_v", False),
                               rotation=ov.get("rotation", 0))
        scale_pct = ov.get("scale", 30) / 100.0
        target_h  = int(H * scale_pct)
        target_w  = int(ov_img.width * (target_h / ov_img.height))
        ov_img    = ov_img.resize((target_w, target_h), Image.LANCZOS)
        pad_x, pad_y = ov.get("offset_x", 20), ov.get("offset_y", 20)
        cx, cy = (W - target_w) // 2, (H - target_h) // 2
        pos = ov.get("position", "br")
        if   pos == "tl": x, y = pad_x, pad_y
        elif pos == "tm": x, y = cx, pad_y
        elif pos == "tr": x, y = W-target_w-pad_x, pad_y
        elif pos == "ml": x, y = pad_x, cy
        elif pos == "cc": x, y = cx, cy
        elif pos == "mr": x, y = W-target_w-pad_x, cy
        elif pos == "bl": x, y = pad_x, H-target_h-pad_y
        elif pos == "bm": x, y = cx, H-target_h-pad_y
        else:             x, y = W-target_w-pad_x, H-target_h-pad_y
        canvas.paste(ov_img, (x, y), ov_img)

    return canvas

def apply_to_explorer(cfg):
    dll = cfg.get("dll_path", "")
    if not dll or not os.path.exists(dll):
        log("DLL not found, skipping apply")
        return False
    try:
        dll_dir   = os.path.dirname(dll)
        image_dir = os.path.join(dll_dir, "image")
        ini_path  = os.path.join(dll_dir, "config.ini")
        os.makedirs(image_dir, exist_ok=True)
        img = composite_final(cfg)
        img.save(os.path.join(image_dir, "bg_custom.png"), "PNG")
        # Write config.ini
        with open(ini_path, "w") as f:
            f.write(f"""[load]
folderExt=false
noerror=false
[image]
random=false
custom=false
posType=6
imgAlpha=255
folder={image_dir}
""")
        result = subprocess.run(["regsvr32", "/s", dll], capture_output=True)
        return result.returncode == 0
    except Exception as e:
        log(f"Apply error: {e}")
        return False

# ── Main watcher loop ─────────────────────────────────────────────────────────
def main():
    log("Wallpaper watcher started")

    last_mtime = get_transcoded_mtime()
    log(f"Initial wallpaper mtime: {last_mtime}")

    while True:
        time.sleep(CHECK_INTERVAL)

        # Re-read config each cycle (user might have changed settings)
        cfg = load_config()

        # Stop if user switched to custom image
        if not cfg.get("wallpaper_mode", False):
            log("wallpaper_mode is off — watcher exiting")
            break

        mtime = get_transcoded_mtime()
        if mtime and mtime != last_mtime:
            log(f"Wallpaper changed! Old mtime: {last_mtime}, new: {mtime}")
            last_mtime = mtime

            # Get new wallpaper
            path = get_desktop_wallpaper()
            if not path:
                log("Could not grab new wallpaper")
                continue

            # Update config with new path
            cfg["image_path"] = path
            save_config(cfg)

            # Apply to Explorer
            ok = apply_to_explorer(cfg)
            log(f"Auto-apply result: {'✅ success' if ok else '❌ failed'}")
        else:
            log(f"No wallpaper change detected (mtime: {mtime})")

    log("Watcher exited")

if __name__ == "__main__":
    main()

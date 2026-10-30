import os
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
SVG_PATH = BASE_DIR / "assets" / "icon.svg"
PNG_1024 = BASE_DIR / "assets" / "icon_1024.png"
PNG_512 = BASE_DIR / "assets" / "icon.png"
ICO_PATH = BASE_DIR / "assets" / "icon.ico"
ICNS_PATH = BASE_DIR / "assets" / "icon.icns"
STATIC_FAVICON = BASE_DIR / "static" / "favicon.ico"
STATIC_ICON_PNG = BASE_DIR / "static" / "icon.png"

svg_code = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
  <defs>
    <!-- Background Gradient -->
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1f2328"/>
      <stop offset="35%" stop-color="#13161a"/>
      <stop offset="100%" stop-color="#08090b"/>
    </linearGradient>

    <!-- Spotify Green Gradient -->
    <linearGradient id="spotifyGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1ed760"/>
      <stop offset="60%" stop-color="#1db954"/>
      <stop offset="100%" stop-color="#149444"/>
    </linearGradient>

    <!-- Accent Cyan Gradient -->
    <linearGradient id="cyanGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8"/>
      <stop offset="100%" stop-color="#0284c7"/>
    </linearGradient>

    <!-- Downward Arrow Gradient -->
    <linearGradient id="arrowGrad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#4ade80"/>
      <stop offset="65%" stop-color="#1ed760"/>
      <stop offset="100%" stop-color="#38bdf8"/>
    </linearGradient>

    <!-- Ambient Glow -->
    <radialGradient id="greenGlow" cx="50%" cy="45%" r="60%">
      <stop offset="0%" stop-color="#1db954" stop-opacity="0.25"/>
      <stop offset="60%" stop-color="#1db954" stop-opacity="0.04"/>
      <stop offset="100%" stop-color="#1db954" stop-opacity="0"/>
    </radialGradient>

    <radialGradient id="cyanGlow" cx="50%" cy="75%" r="45%">
      <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.2"/>
      <stop offset="60%" stop-color="#0284c7" stop-opacity="0.03"/>
      <stop offset="100%" stop-color="#0284c7" stop-opacity="0"/>
    </radialGradient>

    <!-- Soft Drop Shadow for Outer Shell -->
    <filter id="cardShadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="24" stdDeviation="32" flood-color="#000000" flood-opacity="0.7"/>
    </filter>
  </defs>

  <!-- Base App Squircle / Rounded Canvas -->
  <rect x="52" y="52" width="920" height="920" rx="208" ry="208" fill="url(#bgGrad)" filter="url(#cardShadow)"/>
  <!-- Rim Highlight Border -->
  <rect x="52" y="52" width="920" height="920" rx="208" ry="208" fill="none" stroke="rgba(255,255,255,0.12)" stroke-width="3"/>
  <rect x="56" y="56" width="912" height="912" rx="204" ry="204" fill="none" stroke="rgba(29,185,84,0.3)" stroke-width="2"/>

  <!-- Ambient Radial Glows -->
  <rect x="52" y="52" width="920" height="920" rx="208" ry="208" fill="url(#greenGlow)"/>
  <rect x="52" y="52" width="920" height="920" rx="208" ry="208" fill="url(#cyanGlow)"/>

  <!-- Vinyl Turntable Base Disc -->
  <circle cx="512" cy="512" r="375" fill="#101316" stroke="#1c2025" stroke-width="6"/>

  <!-- Subtle Vinyl Grooves -->
  <circle cx="512" cy="512" r="348" fill="none" stroke="rgba(255,255,255,0.03)" stroke-width="2"/>
  <circle cx="512" cy="512" r="322" fill="none" stroke="rgba(255,255,255,0.04)" stroke-width="2"/>
  <circle cx="512" cy="512" r="296" fill="none" stroke="rgba(255,255,255,0.03)" stroke-width="2"/>
  <circle cx="512" cy="512" r="270" fill="none" stroke="rgba(255,255,255,0.04)" stroke-width="2"/>
  <circle cx="512" cy="512" r="244" fill="none" stroke="rgba(255,255,255,0.03)" stroke-width="2"/>
  <circle cx="512" cy="512" r="218" fill="none" stroke="rgba(255,255,255,0.04)" stroke-width="2"/>

  <!-- Center Vinyl Label Circle -->
  <circle cx="512" cy="512" r="185" fill="#16191d" stroke="url(#spotifyGrad)" stroke-width="5"/>

  <!-- Spotify Curved Acoustic Waves (Top) -->
  <!-- Wave 1 (Upper) -->
  <path d="M 335 415 A 235 235 0 0 1 689 415" fill="none" stroke="url(#spotifyGrad)" stroke-width="36" stroke-linecap="round"/>
  <!-- Wave 2 (Middle) -->
  <path d="M 378 472 A 185 185 0 0 1 646 472" fill="none" stroke="url(#spotifyGrad)" stroke-width="30" stroke-linecap="round"/>
  <!-- Wave 3 (Lower) -->
  <path d="M 424 526 A 132 132 0 0 1 600 526" fill="none" stroke="url(#spotifyGrad)" stroke-width="26" stroke-linecap="round"/>

  <!-- Equalizer Spectrum Bars & Downward Audio Stream -->
  <g transform="translate(512, 660)">
    <!-- Left Equalizer bars -->
    <rect x="-165" y="-35" width="16" height="70" rx="8" fill="#38bdf8" opacity="0.85"/>
    <rect x="-125" y="-60" width="16" height="120" rx="8" fill="#38bdf8" opacity="0.95"/>
    <rect x="-85" y="-45" width="16" height="90" rx="8" fill="url(#spotifyGrad)"/>

    <!-- Right Equalizer bars -->
    <rect x="69" y="-45" width="16" height="90" rx="8" fill="url(#spotifyGrad)"/>
    <rect x="109" y="-60" width="16" height="120" rx="8" fill="#38bdf8" opacity="0.95"/>
    <rect x="149" y="-35" width="16" height="70" rx="8" fill="#38bdf8" opacity="0.85"/>

    <!-- Central Glowing Download Arrow -->
    <path d="M 0 -95 L 0 52" fill="none" stroke="url(#arrowGrad)" stroke-width="32" stroke-linecap="round"/>
    <path d="M -48 10 L 0 58 L 48 10" fill="none" stroke="url(#arrowGrad)" stroke-width="32" stroke-linecap="round" stroke-linejoin="round"/>
  </g>
</svg>'''

SVG_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(SVG_PATH, "w", encoding="utf-8") as f:
    f.write(svg_code)

print(f"Saved SVG to {SVG_PATH}")

# Render to 1024x1024 PNG with Playwright
html_content = f'''<!DOCTYPE html>
<html>
<head>
<style>
  body {{
    margin: 0;
    padding: 0;
    background: transparent;
    display: flex;
    justify-content: center;
    align-items: center;
    width: 1024px;
    height: 1024px;
    overflow: hidden;
  }}
  svg {{
    width: 1024px;
    height: 1024px;
  }}
</style>
</head>
<body>
{svg_code}
</body>
</html>'''

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1024, "height": 1024}, device_scale_factor=1)
    page.set_content(html_content)
    page.screenshot(path=str(PNG_1024), omit_background=True)
    browser.close()

print(f"Rendered PNG_1024 to {PNG_1024}")

# Generate standard icon sizes
img = Image.open(PNG_1024)

# 512x512 PNG
img_512 = img.resize((512, 512), Image.Resampling.LANCZOS)
img_512.save(PNG_512, "PNG")
print(f"Saved PNG_512 to {PNG_512}")

# Also copy to static/
img_512.save(STATIC_ICON_PNG, "PNG")

# Generate Windows ICO containing multi-res layers
ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(ICO_PATH, format="ICO", sizes=ico_sizes)
print(f"Saved ICO to {ICO_PATH}")
img.save(STATIC_FAVICON, format="ICO", sizes=ico_sizes)

# Generate macOS ICNS using iconutil on macOS
import subprocess
import tempfile
import shutil

iconset_dir = BASE_DIR / "assets" / "AppIcon.iconset"
iconset_dir.mkdir(parents=True, exist_ok=True)

resolutions = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png")
]

for size, filename in resolutions:
    resized = img.resize((size, size), Image.Resampling.LANCZOS)
    resized.save(iconset_dir / filename, "PNG")

res = subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(ICNS_PATH)])
if res.returncode == 0:
    print(f"Generated macOS ICNS successfully at {ICNS_PATH}")
    shutil.rmtree(iconset_dir)
else:
    print(f"iconutil returned {res.returncode}")

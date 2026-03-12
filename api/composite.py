from PIL import Image, ImageDraw, ImageFont
import textwrap
import requests
import io
import os
import unicodedata
from http.server import BaseHTTPRequestHandler
import json

# Positions du cadre TechSociety (1080x1350)
BADGE_BOTTOM = 799
FOOTER_TOP = 1002
TITLE_START_Y = BADGE_BOTTOM + 25
TITLE_MAX_HEIGHT = FOOTER_TOP - TITLE_START_Y - 20  # ~158px
MAX_W_CHARS = 24
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def clean_text(text):
    return unicodedata.normalize('NFC', text)


def build_composite(article_image_url: str, title: str) -> bytes:
    # 1. Charger le cadre
    frame_path = os.path.join(os.path.dirname(__file__), "..", "frame.png")
    frame = Image.open(frame_path).convert("RGBA")
    W, H = frame.size  # 1080 x 1350

    # 2. Télécharger l'image article
    article_bg = None
    if article_image_url and article_image_url.strip().startswith("http"):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.get(article_image_url.strip(), timeout=20, headers=headers)
            resp.raise_for_status()
            article_bg = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        except Exception as e:
            print(f"Erreur image article: {e}")
            article_bg = None

    # Fallback si image indispo
    if article_bg is None:
        article_bg = Image.new("RGBA", (W, H), (20, 20, 20, 255))

    # 3. Cover : redimensionner pour couvrir tout le fond
    img_ratio = article_bg.width / article_bg.height
    frame_ratio = W / H

    if img_ratio > frame_ratio:
        new_h = H
        new_w = int(H * img_ratio)
    else:
        new_w = W
        new_h = int(W / img_ratio)

    article_resized = article_bg.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - W) // 2
    top = (new_h - H) // 2
    article_cropped = article_resized.crop((left, top, left + W, top + H))

    # 4. Composer : image fond + cadre par-dessus
    composite = Image.new("RGBA", (W, H))
    composite.paste(article_cropped, (0, 0))
    composite.paste(frame, (0, 0), frame)

    # 5. Titre — auto-sizing, minimum 36px, centré sous le badge
    draw = ImageDraw.Draw(composite)
    title = clean_text(title)

    chosen_font = None
    chosen_lines = []
    chosen_line_height = 0

    for font_size in range(52, 34, -2):
        try:
            font = ImageFont.truetype(FONT_PATH, font_size)
        except Exception:
            font = ImageFont.load_default()

        wrapped = textwrap.fill(title, width=MAX_W_CHARS)
        lines = wrapped.split("\n")
        line_height = font_size + 16
        total_height = len(lines) * line_height

        if total_height <= TITLE_MAX_HEIGHT:
            chosen_font = font
            chosen_lines = lines
            chosen_line_height = line_height
            break

    # Fallback minimum 36px — tronquer si nécessaire
    if not chosen_font:
        font_size = 36
        try:
            chosen_font = ImageFont.truetype(FONT_PATH, font_size)
        except Exception:
            chosen_font = ImageFont.load_default()
        wrapped = textwrap.fill(title, width=MAX_W_CHARS)
        all_lines = wrapped.split("\n")
        chosen_line_height = font_size + 16
        max_lines = TITLE_MAX_HEIGHT // chosen_line_height
        chosen_lines = all_lines[:max_lines]
        if len(all_lines) > max_lines and chosen_lines:
            chosen_lines[-1] = chosen_lines[-1][:-3] + "…"

    # Dessin centré avec ombre portée
    y_cursor = TITLE_START_Y
    for line in chosen_lines:
        bbox = draw.textbbox((0, 0), line, font=chosen_font)
        line_w = bbox[2] - bbox[0]
        x = (W - line_w) / 2
        draw.text((x + 2, y_cursor + 2), line, font=chosen_font, fill=(0, 0, 0, 230))
        draw.text((x, y_cursor), line, font=chosen_font, fill=(255, 255, 255, 255))
        y_cursor += chosen_line_height

    # 6. Retourner les bytes JPEG
    output = io.BytesIO()
    composite.convert("RGB").save(output, format="JPEG", quality=92)
    return output.getvalue()


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
            image_url = data.get("image_url", "")
            title = data.get("title", "")

            if not title:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "title is required"}).encode())
                return

            img_bytes = build_composite(image_url, title)

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(img_bytes)))
            self.end_headers()
            self.wfile.write(img_bytes)

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

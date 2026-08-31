"""
Result image renderer — generates the shareable JPG for a tournament
result entirely in memory (no disk/DB/S3 writes), matching the
ClassyBattle brand look used across the app (dark bg, purple brand,
gold winners, green prize amounts).

Patch notes: new file app/services/result_image_service.py.
Requires Pillow (add "Pillow" to requirements.txt if not already present).
"""
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.schemas.public_result import PublicResultDetail

# ---- Brand palette (mirrors the Flutter app's AppColors) ----
BG = (12, 14, 20)
CARD = (20, 22, 31)
BORDER = (255, 255, 255, 20)
TEXT_PRIMARY = (245, 246, 250)
TEXT_SECONDARY = (138, 142, 163)
TEXT_MUTED = (91, 95, 114)
PURPLE = (109, 91, 255)
GOLD = (255, 200, 87)
SILVER = (199, 202, 214)
BRONZE = (255, 159, 67)
GREEN = (47, 217, 123)

WIDTH = 1080
PADDING = 56
FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# Preferred bundled font (ships in app/assets/fonts/, checked into the repo)
# falls back to Inter if present, then to a system font that is confirmed to
# render the ₹ glyph correctly (Poppins/DejaVu Sans do; Pillow's built-in
# default bitmap font does NOT and will show a blank box instead of ₹).
_SYSTEM_FONT_CANDIDATES = {
    False: [
        FONT_DIR / "Inter-Regular.ttf",
        Path("/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ],
    True: [
        FONT_DIR / "Inter-Bold.ttf",
        Path("/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ],
}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in _SYSTEM_FONT_CANDIDATES[bold]:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    # Last resort — will render ₹ as a blank box. Should not be reached in
    # production once a real font is deployed alongside the app.
    return ImageFont.load_default()


def _rounded_rect(draw: ImageDraw.ImageDraw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _rank_color(rank: int):
    return {1: GOLD, 2: SILVER, 3: BRONZE}.get(rank, TEXT_SECONDARY)


class ResultImageService:
    @staticmethod
    def render(detail: PublicResultDetail) -> BytesIO:
        rows_needed = len(detail.winners) + min(len(detail.participants), 40)
        height = 420 + rows_needed * 44 + 140

        img = Image.new("RGB", (WIDTH, height), BG)
        draw = ImageDraw.Draw(img, "RGBA")
        y = PADDING

        # Brand pill
        f_brand = _font(24, bold=True)
        pill_w = draw.textlength("CLASSYBATTLE", font=f_brand) + 48
        _rounded_rect(draw, (WIDTH / 2 - pill_w / 2, y, WIDTH / 2 + pill_w / 2, y + 52), 14, fill=PURPLE)
        draw.text((WIDTH / 2, y + 26), "CLASSYBATTLE", font=f_brand, fill=(255, 255, 255), anchor="mm")
        y += 90

        # Title + subtitle
        f_title = _font(46, bold=True)
        draw.text((WIDTH / 2, y), detail.title, font=f_title, fill=TEXT_PRIMARY, anchor="mm")
        y += 46

        f_sub = _font(24)
        subtitle = f"{detail.starts_at.strftime('%d %B %Y · %I:%M %p')} · RESULT"
        draw.text((WIDTH / 2, y), subtitle, font=f_sub, fill=TEXT_SECONDARY, anchor="mm")
        y += 56

        # Winners card
        card_x0, card_x1 = PADDING, WIDTH - PADDING
        winners_h = 70 + len(detail.winners) * 60
        _rounded_rect(draw, (card_x0, y, card_x1, y + winners_h), 20, fill=CARD, outline=(255, 255, 255, 18), width=1)
        f_label = _font(20, bold=True)
        draw.text((card_x0 + 28, y + 24), "WINNERS", font=f_label, fill=GOLD)
        row_y = y + 66
        f_name = _font(26, bold=True)
        f_amt = _font(26, bold=True)
        for w in detail.winners:
            badge_center = (card_x0 + 46, row_y + 20)
            draw.ellipse(
                (badge_center[0] - 16, badge_center[1] - 16, badge_center[0] + 16, badge_center[1] + 16),
                fill=_rank_color(w.rank or 0),
            )
            draw.text(badge_center, str(w.rank or "-"), font=_font(18, bold=True), fill=(30, 20, 5), anchor="mm")
            label = w.name + (f"  ·  UID {w.game_uid}" if w.game_uid else "")
            draw.text((card_x0 + 74, row_y + 8), label, font=f_name, fill=TEXT_PRIMARY)
            if w.winning_amount is not None:
                amt_text = f"₹{w.winning_amount:,.0f}"
                draw.text((card_x1 - 28, row_y + 8), amt_text, font=f_amt, fill=GREEN, anchor="ra")
            row_y += 60
        y += winners_h + 24

        # Participants card
        shown = detail.participants[:40]
        remaining = max(0, len(detail.participants) - len(shown))
        part_h = 70 + len(shown) * 40 + (30 if remaining else 0)
        _rounded_rect(draw, (card_x0, y, card_x1, y + part_h), 20, fill=CARD, outline=(255, 255, 255, 18), width=1)
        draw.text(
            (card_x0 + 28, y + 24),
            f"PARTICIPANTS · {len(detail.participants)}",
            font=f_label,
            fill=TEXT_MUTED,
        )
        prow_y = y + 66
        f_p = _font(20)
        for p in shown:
            label = p.name + (f"  ·  UID {p.game_uid}" if p.game_uid else "")
            draw.text((card_x0 + 28, prow_y), label, font=f_p, fill=TEXT_SECONDARY)
            if p.kills is not None:
                draw.text((card_x1 - 28, prow_y), f"{p.kills} kills", font=f_p, fill=TEXT_MUTED, anchor="ra")
            prow_y += 40
        if remaining:
            draw.text((card_x0 + 28, prow_y), f"+{remaining} more", font=f_p, fill=TEXT_MUTED)
            prow_y += 30
        y += part_h + 24

        # Footer
        f_footer = _font(18)
        draw.text(
            (card_x0, y),
            f"Total Prize Pool: ₹{detail.prize_pool:,.0f}",
            font=f_footer,
            fill=TEXT_MUTED,
        )
        draw.text((card_x1, y), "result.classybattle.online", font=f_footer, fill=TEXT_MUTED, anchor="ra")

        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=92)
        buffer.seek(0)
        return buffer

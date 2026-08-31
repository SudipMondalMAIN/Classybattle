"""
Result image renderer — generates the shareable JPG for a tournament
result entirely in memory (no disk/DB/S3 writes).

Layout matches the ClassyBattle "RESULT" poster brand template:
  - header band with brand name, RESULT title, tournament title/date/time bar
  - two-column body: PARTICIPANTS LIST (left) / WINNER LIST (right)
  - footer thank-you strip

Patch notes: replaces app/services/result_image_service.py.
Requires Pillow (already in requirements.txt).
"""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.schemas.public_result import PublicResultDetail

# ---- Brand palette ----
BG = (10, 6, 18)
PANEL = (18, 10, 32)
BAR = (30, 18, 50)
PURPLE = (124, 58, 237)
PURPLE_L = (167, 139, 250)
GOLD = (246, 196, 69)
SILVER = (201, 209, 224)
BRONZE = (217, 138, 74)
TEXT = (233, 228, 245)
MUTED = (155, 141, 201)
DIM = (122, 110, 163)
LINE = (99, 78, 158)
ROW_LINE = (58, 46, 92)

WIDTH = 1040
PADDING = 26
MAX_PARTICIPANTS_SHOWN = 40

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
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
    return ImageFont.load_default()


def _rounded(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _center(draw, xc, y, text, font, fill, anchor="mm"):
    draw.text((xc, y), text, font=font, fill=fill, anchor=anchor)


def _rank_color(rank):
    return {1: GOLD, 2: SILVER, 3: BRONZE}.get(rank, MUTED)


def _position_label(rank, total):
    """Derives a TOP N bucket label the way the brand template shows it."""
    if rank is None:
        return "-"
    if rank <= 10:
        return "TOP 10"
    if rank <= 50:
        return "TOP 50"
    if rank <= 100:
        return "TOP 100"
    return f"#{rank}"


def _money(amount) -> str:
    return f"\u20b9{amount:,.0f}" if amount is not None else "-"


def _clean(name) -> str:
    """Player display names commonly include a decorative star (e.g.
    "CB\u2605LEGEND") that the bundled font doesn't ship a glyph for, which
    renders as a blank box. Swap it for a hyphen so it always renders."""
    name = name or "Player"
    return name.replace("\u2605", "-").replace("\u2606", "-")


class ResultImageService:
    @staticmethod
    def render(detail: PublicResultDetail) -> BytesIO:
        f_brand = _font(30, bold=True)
        f_tag = _font(11, bold=True)
        f_title = _font(66, bold=True)
        f_eyebrow = _font(11, bold=True)
        f_tourney = _font(18, bold=True)
        f_meta = _font(14)
        f_panel = _font(15, bold=True)
        f_th = _font(11, bold=True)
        f_td = _font(13)
        f_td_b = _font(13, bold=True)
        f_wname = _font(15, bold=True)
        f_wsub = _font(11)
        f_wsub_b = _font(11, bold=True)
        f_reward_l = _font(9, bold=True)
        f_reward = _font(15, bold=True)
        f_footer = _font(14, bold=True)
        f_footer_s = _font(10)

        winners = sorted(detail.winners, key=lambda w: (w.rank or 999))
        participants = sorted(detail.participants, key=lambda p: (p.rank or 999))
        shown_participants = participants[:MAX_PARTICIPANTS_SHOWN]
        remaining = max(0, len(participants) - len(shown_participants))

        row_h_p = 30
        row_h_w = 96
        p_rows_h = len(shown_participants) * row_h_p + (26 if remaining else 0)
        w_rows_h = len(winners) * row_h_w
        col_h = max(p_rows_h, w_rows_h) + 70
        body_top = 306
        footer_h = 130
        height = body_top + col_h + 30 + footer_h

        img = Image.new("RGB", (WIDTH, height), BG)
        d = ImageDraw.Draw(img)

        # ---- hero ----
        d.rectangle((0, 0, WIDTH, 300), fill=(18, 10, 30))
        d.line([(0, 300), (WIDTH, 300)], fill=LINE, width=2)

        bx, by = WIDTH // 2 - 130, 34
        _rounded(d, (bx, by, bx + 50, by + 50), 8, outline=PURPLE_L, width=2)
        _center(d, bx + 25, by + 25, "CB", _font(20, bold=True), (255, 255, 255))
        d.text((bx + 62, by), "Classy", font=f_brand, fill=(255, 255, 255))
        w_classy = d.textlength("Classy", font=f_brand)
        d.text((bx + 62 + w_classy, by), "Battle", font=f_brand, fill=PURPLE_L)

        _center(d, WIDTH // 2, 100, "C O M P E T E   \u2022   W I N   \u2022   R E P E A T", f_tag, (184, 174, 224))
        _center(d, WIDTH // 2, 178, "RESULT", f_title, (240, 235, 250))

        mb = (46, 224, WIDTH - 46, 274)
        _rounded(d, mb, 10, outline=LINE, width=2, fill=BAR)
        d.text((66, 232), "TOURNAMENT TITLE", font=f_eyebrow, fill=PURPLE_L)
        title_text = detail.title.upper()
        d.text((66, 248), title_text, font=f_tourney, fill=(255, 255, 255))
        date_str = detail.starts_at.strftime("%d %B %Y").upper()
        time_str = detail.starts_at.strftime("%I:%M %p IST").upper()
        d.text((WIDTH - 320, 242), f"DATE: {date_str}", font=f_meta, fill=(216, 208, 239))
        d.line([(WIDTH - 150, 236), (WIDTH - 150, 262)], fill=LINE, width=1)
        d.text((WIDTH - 134, 242), f"TIME: {time_str}", font=f_meta, fill=(216, 208, 239))

        # ---- body columns ----
        col_gap = 20
        col_w = (WIDTH - 2 * PADDING - col_gap) // 2
        left_x0 = PADDING
        right_x0 = left_x0 + col_w + col_gap
        top = body_top

        def panel(x0, y0, w, h, title):
            _rounded(d, (x0, y0, x0 + w, y0 + h), 12, outline=LINE, width=2, fill=PANEL)
            _center(d, x0 + w // 2, y0 + 24, title, f_panel, PURPLE_L)
            return x0 + 16, y0 + 48

        # participants panel
        px0, py0 = panel(left_x0, top, col_w, col_h, f"PARTICIPANTS LIST ({len(participants)})")
        px1 = left_x0 + col_w - 16
        cols = [px0, px0 + 30, px0 + 150, px0 + 268, px0 + 358]
        for cx, htext in zip(cols, ["#", "PLAYER NAME", "UID", "ELIM.", "POSITION"]):
            d.text((cx, py0), htext, font=f_th, fill=(168, 155, 214))
        hy = py0 + 18
        d.line([(px0, hy), (px1, hy)], fill=LINE, width=1)
        ry = hy + 12
        for idx, p in enumerate(shown_participants, start=1):
            pos_label = _position_label(p.rank or idx, len(participants))
            d.text((cols[0], ry), str(p.rank or idx), font=f_td, fill=MUTED)
            d.text((cols[1], ry), _clean(p.name)[:16], font=f_td, fill=TEXT)
            d.text((cols[2], ry), p.game_uid or "-", font=f_td, fill=TEXT)
            d.text((cols[3], ry), str(p.kills if p.kills is not None else "-"), font=f_td, fill=TEXT)
            d.text((cols[4], ry), pos_label, font=f_td_b, fill=PURPLE_L)
            ry += row_h_p
            d.line([(px0, ry - 8), (px1, ry - 8)], fill=ROW_LINE)
        if remaining:
            d.text((px0, ry), f"+{remaining} more", font=f_td, fill=DIM)

        # winners panel
        wx0, wy0 = panel(right_x0, top, col_w, col_h, "WINNER LIST")
        wx1 = right_x0 + col_w - 16
        wy = wy0
        for i, w in enumerate(winners):
            rank = w.rank or (i + 1)
            box_y0 = wy
            box_y1 = wy + row_h_w - 12
            cy = box_y0 + (box_y1 - box_y0) // 2
            cx = wx0 + 18
            rcolor = _rank_color(rank)
            d.ellipse((cx - 18, cy - 18, cx + 18, cy + 18), outline=rcolor, width=2,
                      fill=(rcolor[0] // 6, rcolor[1] // 6, rcolor[2] // 6))
            _center(d, cx, cy, str(rank), f_reward, rcolor)

            ax0 = wx0 + 46
            _rounded(d, (ax0, cy - 18, ax0 + 36, cy + 18), 8, outline=LINE, width=1, fill=(45, 32, 72))

            tx = ax0 + 50
            d.text((tx, cy - 24), _clean(w.name)[:20], font=f_wname, fill=(255, 255, 255))
            sub = f"UID: {w.game_uid or '-'}   |   ELIMINATIONS "
            d.text((tx, cy + 2), sub, font=f_wsub, fill=MUTED)
            subw = d.textlength(sub, font=f_wsub)
            elim_val = str(w.kills) if w.kills is not None else "-"
            d.text((tx + subw, cy + 2), elim_val, font=f_wsub_b, fill=PURPLE_L)

            rx = wx1 - 6
            d.text((rx, cy - 20), "REWARD", font=f_reward_l, fill=DIM, anchor="ra")
            d.text((rx, cy - 2), _money(w.winning_amount), font=f_reward, fill=GOLD, anchor="ra")

            wy += row_h_w
            if i != len(winners) - 1:
                d.line([(wx0, wy - 12), (wx1, wy - 12)], fill=ROW_LINE)

        # ---- footer ----
        fy = top + col_h + 30
        d.line([(16, fy), (WIDTH - 16, fy)], fill=LINE, width=2)
        _center(d, WIDTH // 2, fy + 32, "THANK YOU TO ALL THE PARTICIPANTS!", f_footer, PURPLE_L)
        _center(d, WIDTH // 2, fy + 54, "STAY TUNED FOR MORE EXCITING TOURNAMENTS ONLY ON", f_footer_s, (139, 127, 181))
        fbx, fby = WIDTH // 2 - 66, fy + 76
        _rounded(d, (fbx, fby, fbx + 28, fby + 28), 6, outline=PURPLE_L, width=2)
        _center(d, fbx + 14, fby + 14, "CB", _font(12, bold=True), (255, 255, 255))
        f_fb = _font(16, bold=True)
        d.text((fbx + 38, fby + 4), "Classy", font=f_fb, fill=(255, 255, 255))
        w2 = d.textlength("Classy", font=f_fb)
        d.text((fbx + 38 + w2, fby + 4), "Battle", font=f_fb, fill=PURPLE_L)

        buffer = BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=92)
        buffer.seek(0)
        return buffer
"""
Result image renderer -- generates the shareable JPG for a tournament
result entirely in memory (no disk/DB/S3 writes).

Layout matches the ClassyBattle "RESULT" poster brand template:
  - header band with brand name, RESULT title, tournament title/date/time bar
  - two-column body: PARTICIPANTS LIST (left) / WINNER LIST (right)
  - footer thank-you strip

The columns shown adapt to the tournament's prize_type so the card never
shows a field that isn't relevant to how the tournament was scored:
  - "rank"     -> POSITION only (no eliminations, no win badge)
  - "per_kill" -> KILLS only (no position, no win badge)
  - "win"      -> WIN status only (no position, no eliminations)
Prize money is always shown -- that's true regardless of scoring mode.

Quality: the whole poster is drawn at 2.5x scale (supersampled) and then
downsampled with a high-quality filter, so edges/circles/rounded panels
come out anti-aliased instead of jagged, and the final JPEG is sharper at
a larger native resolution. Fonts are bundled in the repo
(app/assets/fonts) so rendering never silently falls back to Pillow's
tiny bitmap default font, which was the main cause of the poster looking
low-quality / broken on hosts (like Render) that don't ship system fonts.

Patch notes: replaces app/services/result_image_service.py.
Requires Pillow (already in requirements.txt).
"""
from io import BytesIO
from pathlib import Path
from typing import Optional

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
WIN_GREEN = (74, 222, 128)

# ---- Resolution ----
# Everything below is designed in this "logical" 1040-wide coordinate
# space (same as before), then SCALE blows every number up before
# drawing, and the finished poster is downsampled to FINAL_WIDTH with a
# high-quality filter. That supersampling is what actually removes the
# jagged edges on circles/rounded panels/lines -- Pillow's ImageDraw
# shapes aren't anti-aliased on their own.
LOGICAL_WIDTH = 1040
SCALE = 2.5
FINAL_WIDTH = 1300  # slightly larger than the old 1040 output too

PADDING = 26
MAX_PARTICIPANTS_SHOWN = 40

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "images" / "logo.png"
_LOGO_CACHE: dict[int, Image.Image] = {}


def _logo(size: int) -> Optional[Image.Image]:
    """Loads the bundled ClassyBattle logo, scaled to `size` (px, in the
    *supersampled* canvas -- pass an already-S()'d value), resampled once
    per size and cached. Returns None if the asset is missing so callers
    can fall back gracefully instead of crashing the render."""
    if size in _LOGO_CACHE:
        return _LOGO_CACHE[size]
    if not LOGO_PATH.exists():
        return None
    try:
        img = Image.open(LOGO_PATH).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
    except OSError:
        return None
    _LOGO_CACHE[size] = img
    return img


def _paste_logo(canvas: Image.Image, cx: float, cy: float, diameter: float) -> bool:
    """Pastes the logo centered at logical (cx, cy) with the given logical
    diameter. Returns True if it actually drew something, so callers can
    fall back to the old text badge when the asset isn't bundled."""
    size = max(1, round(S(diameter)))
    logo = _logo(size)
    if logo is None:
        return False
    x0 = round(S(cx) - size / 2)
    y0 = round(S(cy) - size / 2)
    canvas.paste(logo, (x0, y0), logo)
    return True
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

_FONT_CACHE: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def S(v: float) -> float:
    """Scale a logical-space number into the supersampled canvas."""
    return v * SCALE


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load a bundled/system font at a *scaled* pixel size, with a safe
    fallback chain so a missing font file can never crash the render --
    worst case it degrades to Pillow's built-in default font instead of
    throwing a 500."""
    scaled_size = max(1, round(S(size)))
    cache_key = (scaled_size, bold)
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]
    for path in _SYSTEM_FONT_CANDIDATES[bold]:
        try:
            if path.exists():
                font = ImageFont.truetype(str(path), scaled_size)
                _FONT_CACHE[cache_key] = font
                return font
        except OSError:
            continue
    font = ImageFont.load_default()
    _FONT_CACHE[cache_key] = font
    return font


def _rounded(draw, box, radius, fill=None, outline=None, width=1):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(
        (S(x0), S(y0), S(x1), S(y1)), radius=S(radius), fill=fill, outline=outline,
        width=max(1, round(S(width))),
    )


def _line(draw, points, fill, width=1):
    scaled = [(S(x), S(y)) for x, y in points]
    draw.line(scaled, fill=fill, width=max(1, round(S(width))))


def _ellipse(draw, box, outline=None, fill=None, width=1):
    x0, y0, x1, y1 = box
    draw.ellipse(
        (S(x0), S(y0), S(x1), S(y1)), outline=outline, fill=fill,
        width=max(1, round(S(width))),
    )


def _rect(draw, box, fill=None):
    x0, y0, x1, y1 = box
    draw.rectangle((S(x0), S(y0), S(x1), S(y1)), fill=fill)


def _text(draw, xy, text, font, fill, anchor=None):
    x, y = xy
    draw.text((S(x), S(y)), text, font=font, fill=fill, anchor=anchor)


def _center(draw, xc, y, text, font, fill, anchor="mm"):
    _text(draw, (xc, y), text, font, fill, anchor=anchor)


def _textlength(draw, text, font) -> float:
    """Returns the width back in *logical* units so callers can keep
    doing layout math in the same coordinate space as everything else."""
    return draw.textlength(text, font=font) / SCALE


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
        # "rank" | "per_kill" | "win" -- decides which stat column shows.
        # Anything unrecognized safely falls back to "rank" behaviour.
        mode = (detail.prize_type or "rank").lower()
        if mode not in ("rank", "per_kill", "win"):
            mode = "rank"
        show_position = mode == "rank"
        show_kills = mode == "per_kill"
        show_win = mode == "win"

        WIDTH = LOGICAL_WIDTH

        f_brand = _font(30, bold=True)
        f_tag = _font(11, bold=True)
        f_title = _font(66, bold=True)
        f_eyebrow = _font(11, bold=True)
        f_tourney = _font(18, bold=True)
        f_meta = _font(14)
        f_panel = _font(15, bold=True)
        f_th = _font(11, bold=True)
        f_td = _font(13)
        f_td_uid = _font(10)
        f_td_b = _font(13, bold=True)
        f_wname = _font(15, bold=True)
        f_wsub = _font(11)
        f_wsub_b = _font(11, bold=True)
        f_reward_l = _font(9, bold=True)
        f_reward = _font(15, bold=True)
        f_footer = _font(14, bold=True)
        f_footer_s = _font(10)
        f_badge = _font(13, bold=True)

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

        img = Image.new("RGB", (round(S(WIDTH)), round(S(height))), BG)
        d = ImageDraw.Draw(img)

        # ---- hero ----
        _rect(d, (0, 0, WIDTH, 300), fill=(18, 10, 30))
        _line(d, [(0, 300), (WIDTH, 300)], fill=LINE, width=2)

        bx, by = WIDTH // 2 - 130, 34
        if not _paste_logo(img, bx + 25, by + 25, 50):
            _rounded(d, (bx, by, bx + 50, by + 50), 8, outline=PURPLE_L, width=2)
            _center(d, bx + 25, by + 25, "CB", _font(20, bold=True), (255, 255, 255))
        _text(d, (bx + 62, by), "Classy", f_brand, (255, 255, 255))
        w_classy = _textlength(d, "Classy", f_brand)
        _text(d, (bx + 62 + w_classy, by), "Battle", f_brand, PURPLE_L)

        _center(d, WIDTH // 2, 100, "C O M P E T E   \u2022   W I N   \u2022   R E P E A T", f_tag, (184, 174, 224))
        _center(d, WIDTH // 2, 178, "RESULT", f_title, (240, 235, 250))

        mb = (46, 224, WIDTH - 46, 274)
        _rounded(d, mb, 10, outline=LINE, width=2, fill=BAR)
        _text(d, (66, 232), "TOURNAMENT TITLE", f_eyebrow, PURPLE_L)
        title_text = detail.title.upper()
        _text(d, (66, 248), title_text, f_tourney, (255, 255, 255))
        date_str = detail.starts_at.strftime("%d %B %Y").upper()
        time_str = detail.starts_at.strftime("%I:%M %p IST").upper()
        date_label = f"DATE: {date_str}"
        time_label = f"TIME: {time_str}"
        # Right-align both labels off the panel edge, with the divider
        # placed by actual measured text width instead of fixed offsets
        # -- long month names (e.g. "SEPTEMBER") used to run into the
        # divider/time label at the old fixed positions.
        time_w = _textlength(d, time_label, f_meta)
        time_x = WIDTH - 66 - time_w
        divider_x = time_x - 16
        date_x = divider_x - 16 - _textlength(d, date_label, f_meta)
        _text(d, (date_x, 242), date_label, f_meta, (216, 208, 239))
        _line(d, [(divider_x, 236), (divider_x, 262)], fill=LINE, width=1)
        _text(d, (time_x, 242), time_label, f_meta, (216, 208, 239))

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

        # participants panel -- last column adapts to scoring mode
        stat_header = "POSITION" if show_position else ("KILLS" if show_kills else "RESULT")
        px0, py0 = panel(left_x0, top, col_w, col_h, f"PARTICIPANTS LIST ({len(participants)})")
        px1 = left_x0 + col_w - 16
        cols = [px0, px0 + 30, px0 + 150, px0 + 300]
        headers = ["#", "PLAYER NAME", "GAME UID / CB UID", stat_header]
        for cx, htext in zip(cols, headers):
            _text(d, (cx, py0), htext, f_th, (168, 155, 214))
        hy = py0 + 18
        _line(d, [(px0, hy), (px1, hy)], fill=LINE, width=1)
        ry = hy + 12
        for idx, p in enumerate(shown_participants, start=1):
            _text(d, (cols[0], ry), str(p.rank or idx), f_td, MUTED)
            _text(d, (cols[1], ry), _clean(p.name)[:18], f_td, TEXT)
            uid_line = f"{p.game_uid or '-'} / {p.player_uid or '-'}"
            _text(d, (cols[2], ry + 1), uid_line, f_td_uid, MUTED)
            if show_position:
                stat_val = _position_label(p.rank or idx, len(participants))
            elif show_kills:
                stat_val = str(p.kills if p.kills is not None else "-")
            else:
                stat_val = "WIN" if p.is_winner else "-"
            stat_color = WIN_GREEN if (show_win and p.is_winner) else PURPLE_L
            _text(d, (cols[3], ry), stat_val, f_td_b, stat_color)
            ry += row_h_p
            _line(d, [(px0, ry - 8), (px1, ry - 8)], fill=ROW_LINE)
        if remaining:
            _text(d, (px0, ry), f"+{remaining} more", f_td, DIM)

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

            if show_win:
                badge_color = WIN_GREEN
                badge_text = "WIN"
                badge_font = f_badge
            elif show_kills:
                badge_color = PURPLE_L
                badge_text = str(w.kills if w.kills is not None else "-")
                badge_font = f_reward
            else:
                badge_color = _rank_color(rank)
                badge_text = str(rank)
                badge_font = f_reward

            _ellipse(
                d, (cx - 18, cy - 18, cx + 18, cy + 18), outline=badge_color, width=2,
                fill=(badge_color[0] // 6, badge_color[1] // 6, badge_color[2] // 6),
            )
            _center(d, cx, cy, badge_text, badge_font, badge_color)

            ax0 = wx0 + 46
            _rounded(d, (ax0, cy - 18, ax0 + 36, cy + 18), 8, outline=LINE, width=1, fill=(45, 32, 72))

            tx = ax0 + 50
            _text(d, (tx, cy - 24), _clean(w.name)[:20], f_wname, (255, 255, 255))

            if show_kills:
                sub = f"UID: {w.game_uid or '-'} / CB: {w.player_uid or '-'}   |   ELIMINATIONS "
                _text(d, (tx, cy + 2), sub, f_wsub, MUTED)
                subw = _textlength(d, sub, f_wsub)
                elim_val = str(w.kills) if w.kills is not None else "-"
                _text(d, (tx + subw, cy + 2), elim_val, f_wsub_b, PURPLE_L)
            else:
                sub = f"UID: {w.game_uid or '-'} / CB: {w.player_uid or '-'}"
                _text(d, (tx, cy + 2), sub, f_wsub, MUTED)

            rx = wx1 - 6
            _text(d, (rx, cy - 20), "REWARD", f_reward_l, DIM, anchor="ra")
            _text(d, (rx, cy - 2), _money(w.winning_amount), f_reward, GOLD, anchor="ra")

            wy += row_h_w
            if i != len(winners) - 1:
                _line(d, [(wx0, wy - 12), (wx1, wy - 12)], fill=ROW_LINE)

        # ---- footer ----
        fy = top + col_h + 30
        _line(d, [(16, fy), (WIDTH - 16, fy)], fill=LINE, width=2)
        _center(d, WIDTH // 2, fy + 32, "THANK YOU TO ALL THE PARTICIPANTS!", f_footer, PURPLE_L)
        _center(d, WIDTH // 2, fy + 54, "STAY TUNED FOR MORE EXCITING TOURNAMENTS ONLY ON", f_footer_s, (139, 127, 181))
        fbx, fby = WIDTH // 2 - 66, fy + 76
        if not _paste_logo(img, fbx + 14, fby + 14, 28):
            _rounded(d, (fbx, fby, fbx + 28, fby + 28), 6, outline=PURPLE_L, width=2)
            _center(d, fbx + 14, fby + 14, "CB", _font(12, bold=True), (255, 255, 255))
        f_fb = _font(16, bold=True)
        _text(d, (fbx + 38, fby + 4), "Classy", f_fb, (255, 255, 255))
        w2 = _textlength(d, "Classy", f_fb)
        _text(d, (fbx + 38 + w2, fby + 4), "Battle", f_fb, PURPLE_L)

        # Downsample the supersampled canvas -- this is what actually
        # smooths the jagged edges on circles/rounded rects/lines, since
        # ImageDraw doesn't anti-alias shapes on its own.
        final_height = round(height * (FINAL_WIDTH / WIDTH))
        img = img.resize((FINAL_WIDTH, final_height), Image.LANCZOS)

        buffer = BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=95, subsampling=0, optimize=True)
        buffer.seek(0)
        return buffer

# Result Site Backend Patch — for result.classybattle.online

This folder contains the backend additions needed to power the public
result site. All files go into the **Classybattle** (main backend) repo.

## Files to add

| File (this folder) | Destination in Classybattle repo |
|---|---|
| `public_result_routes.py` | `app/api/v1/public_result_routes.py` |
| `public_result.py` | `app/schemas/public_result.py` |
| `result_image_service.py` | `app/services/result_image_service.py` |

## Wiring

1. **Register the router** in `app/api/v1/router.py` (same pattern as the
   other `*_routes.py` includes already there — the router variable in
   this repo is named `api_v1_router`, not `api_router`):

   ```python
   from app.api.v1.public_result_routes import router as public_result_router
   api_v1_router.include_router(public_result_router)
   ```

2. **Add Pillow** to `requirements.txt` (if not already present):

   ```
   Pillow>=10.0.0
   ```

3. **Bundle a font** (recommended) at `app/assets/fonts/Inter-Regular.ttf`
   and `app/assets/fonts/Inter-Bold.ttf`. The renderer already falls back
   to Poppins/DejaVu Sans if those aren't present (both correctly render
   the ₹ glyph — Pillow's built-in default font does NOT and will show a
   blank box instead), but shipping the app's real brand font gives a
   pixel-perfect match with the Flutter app's typography.

## Why these are safe to expose publicly

- Every route is read-only and requires **no authentication**.
- `_get_approved_result()` filters strictly on
  `TournamentResult.status == APPROVED` — a result that's only
  `submitted` or `verified` (not yet admin-approved) is never visible
  here. This is the same gate that already exists in the repo's result
  lifecycle (`tournament_result_service.py`), just re-used as the
  public-visibility check.
- `PublicPlayerEntry` only ever carries `name`, `game_uid`, `kills`,
  `rank`, and `winning_amount` — never email, phone, wallet balance, or
  payment details (see `app/schemas/public_result.py`).
- The image endpoint generates JPEG bytes in memory (`BytesIO`) and
  streams them directly in the HTTP response — nothing is written to
  disk, the database, or object storage. Nothing to clean up, nothing
  that can leak via a forgotten file.

## Testing this patch

```bash
pip install Pillow pydantic --break-system-packages
python -c "
from datetime import datetime
from decimal import Decimal
from app.schemas.public_result import PublicResultDetail, PublicPlayerEntry
from app.services.result_image_service import ResultImageService

detail = PublicResultDetail(
    tournament_id='11111111-1111-1111-1111-111111111111',
    tournament_uid='abc123', title='Free Fire Solo Clash',
    starts_at=datetime(2026,8,24,10,0), prize_pool=Decimal('2100'),
    winners=[PublicPlayerEntry(name='ProGamer_Rahul', game_uid='1023948123', is_winner=True, rank=1, winning_amount=Decimal('1200'))],
    participants=[PublicPlayerEntry(name='Player1', game_uid='1000', kills=3)],
)
open('/tmp/test.jpg','wb').write(ResultImageService.render(detail).read())
"
```

## Caching (added)

`public_result_routes.py` now reuses the repo's existing Redis cache
layer (`app/core/cache.py`) so repeated requests for the same — usually
old, unchanging — result don't hit Postgres every time:

- Result detail & image: cached **7 days** (an approved result is
  effectively immutable).
- Result list: cached **60 seconds** (new results get approved over
  time, so this stays fresher).
- Fails open exactly like the rest of the repo's caching: if
  `REDIS_URL` isn't set, or Redis is briefly down, every request just
  falls through to the DB/Pillow render as before — nothing breaks,
  it's purely an optimization.
- No new environment variables or infrastructure needed — it's the
  same Redis instance already used for rate limiting.

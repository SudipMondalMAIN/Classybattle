"""
Custom Match Claim routes — self-declared win/loss results for 1v1
Custom Tournaments, plus the admin review queue for disputed/pending
WIN claims. See app/models/custom_match_claim.py for the full rules.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException
from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.custom_match_claim import (
    CustomMatchClaimPairRead,
    CustomMatchClaimRead,
    PendingClaimAdminRead,
    RejectClaimRequest,
    SubmitClaimRequest,
)
from app.services.custom_match_claim_service import CustomMatchClaimService
from app.storage.storage_service import StorageService

router = APIRouter(tags=["Custom Match Claims"])

_ALLOWED_PROOF_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_PROOF_SIZE_BYTES = 5 * 1024 * 1024


@router.post(
    "/tournaments/{tournament_id}/custom-result/proof",
    response_model=MessageResponse,
)
async def upload_result_proof(
    tournament_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_verified_user),
):
    """Uploads a win-claim screenshot and returns its URL -- call this
    first, then pass the returned url as proof_url on the submit-claim
    request below."""
    if file.content_type not in _ALLOWED_PROOF_CONTENT_TYPES:
        raise ValidationException("Unsupported file type. Allowed types: JPEG, PNG, WEBP")
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise ValidationException("Uploaded file is empty")
    if len(file_bytes) > _MAX_PROOF_SIZE_BYTES:
        raise ValidationException("File is too large. Maximum size is 5 MB")

    from uuid import uuid4

    storage = StorageService(bucket="tournament-assets")
    extension = file.content_type.split("/")[-1]
    path = (
        f"tournaments/{tournament_id}/result-proof-"
        f"{current_user.id}-{uuid4().hex[:8]}.{extension}"
    )
    url = await storage.upload_file(path, file_bytes, file.content_type)
    return MessageResponse(message=url)


@router.post(
    "/tournaments/{tournament_id}/custom-result",
    response_model=CustomMatchClaimPairRead,
)
async def submit_custom_result(
    tournament_id: UUID,
    payload: SubmitClaimRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = CustomMatchClaimService(session)
    return await service.submit_claim(
        tournament_id,
        current_user=current_user,
        outcome=payload.outcome,
        proof_url=payload.proof_url,
    )


@router.get(
    "/tournaments/{tournament_id}/custom-result",
    response_model=CustomMatchClaimPairRead,
)
async def get_custom_result(
    tournament_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = CustomMatchClaimService(session)
    return await service.get_claim_pair(tournament_id, current_user.id)


@router.get(
    "/admin/custom-results/pending",
    response_model=list[PendingClaimAdminRead],
)
async def list_pending_custom_results(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = CustomMatchClaimService(session)
    items, _total = await service.list_pending(page=page, page_size=page_size)
    return items


@router.post(
    "/admin/custom-results/{claim_id}/approve",
    response_model=CustomMatchClaimRead,
)
async def approve_custom_result(
    claim_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = CustomMatchClaimService(session)
    return await service.approve(claim_id, admin)


@router.post(
    "/admin/custom-results/{claim_id}/reject",
    response_model=CustomMatchClaimRead,
)
async def reject_custom_result(
    claim_id: UUID,
    payload: RejectClaimRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = CustomMatchClaimService(session)
    return await service.reject(claim_id, reason=payload.reason, admin=admin)

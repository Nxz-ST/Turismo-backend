from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import AdminUser, CurrentUser, SettingsDep
from app.core.errors import ExternalServiceError, ResourceNotFoundError
from app.schemas.benefit import AgencyAccountRequest, AgencyMemberRequest, BenefitClaimRequest, BenefitTransitionRequest
from app.services.auth import SupabaseAuthService
from app.services.supabase import SupabaseRepository


router = APIRouter()


async def _membership_or_403(repository: SupabaseRepository, user: CurrentUser):
    membership = await repository.agency_membership(user.id)
    if not membership or (membership.get("agency") or {}).get("status") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta cuenta no está vinculada a una agencia activa",
        )
    return membership


@router.get("/session")
async def benefit_session(user: CurrentUser, settings: SettingsDep):
    if user.is_admin:
        return {"role": "admin", "email": user.email}
    membership = await SupabaseRepository(settings).agency_membership(user.id)
    if membership:
        return {
            "role": "agency",
            "email": user.email,
            "member_role": membership["member_role"],
            "agency": membership["agency"],
        }
    return {"role": "user", "email": user.email}


@router.get("/places/{place_source}/{place_id}")
async def place_benefits(
    place_source: str,
    place_id: str,
    user: CurrentUser,
    settings: SettingsDep,
    place_name: str = Query(min_length=1, max_length=180),
):
    if place_source not in {"official", "community"}:
        raise HTTPException(status_code=422, detail="Origen de lugar no válido")
    return await SupabaseRepository(settings).list_benefits_for_place(
        place_source=place_source,
        place_id=place_id,
        place_name=place_name,
    )


@router.post("/{benefit_id}/claim")
async def claim_benefit(
    benefit_id: UUID,
    payload: BenefitClaimRequest,
    user: CurrentUser,
    settings: SettingsDep,
):
    repository = SupabaseRepository(settings)
    try:
        benefit = await repository.get_benefit(benefit_id)
        agency = benefit.get("agency") or {}
        if agency.get("status") != "active":
            raise HTTPException(status_code=409, detail="La agencia no está disponible")
        existing = await repository.active_benefit_redemption(
            user_id=user.id,
            benefit_id=benefit_id,
            place_source=payload.place_source,
            place_id=payload.place_id,
        )
        if existing:
            return existing
        return await repository.create_benefit_redemption(
            user_id=user.id,
            benefit=benefit,
            place_source=payload.place_source,
            place_id=payload.place_id,
            place_name=payload.place_name,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/me/redemptions")
async def my_redemptions(user: CurrentUser, settings: SettingsDep):
    return await SupabaseRepository(settings).list_user_redemptions(user.id)


@router.get("/agency/redemptions")
async def agency_redemptions(
    user: CurrentUser,
    settings: SettingsDep,
    redemption_status: str | None = Query(default=None, alias="status"),
):
    if redemption_status and redemption_status not in {
        "requested", "confirmed", "redeemed", "cancelled", "expired"
    }:
        raise HTTPException(status_code=422, detail="Estado no válido")
    repository = SupabaseRepository(settings)
    membership = await _membership_or_403(repository, user)
    return await repository.list_agency_redemptions(
        membership["agency_id"], status_filter=redemption_status
    )


@router.get("/agency/redemptions/{code}")
async def agency_redemption(code: str, user: CurrentUser, settings: SettingsDep):
    repository = SupabaseRepository(settings)
    membership = await _membership_or_403(repository, user)
    try:
        return await repository.agency_redemption_by_code(
            agency_id=membership["agency_id"], code=code
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/agency/redemptions/{code}/status")
async def transition_agency_redemption(
    code: str,
    payload: BenefitTransitionRequest,
    user: CurrentUser,
    settings: SettingsDep,
):
    repository = SupabaseRepository(settings)
    membership = await _membership_or_403(repository, user)
    try:
        redemption = await repository.agency_redemption_by_code(
            agency_id=membership["agency_id"], code=code
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    allowed = {
        "requested": {"confirmed", "cancelled"},
        "confirmed": {"redeemed", "cancelled"},
        "redeemed": set(),
        "cancelled": set(),
        "expired": set(),
    }
    if payload.status not in allowed.get(redemption["status"], set()):
        raise HTTPException(
            status_code=409,
            detail=f"No se puede pasar de {redemption['status']} a {payload.status}",
        )
    return await repository.transition_benefit_redemption(
        redemption=redemption,
        actor_user_id=user.id,
        target_status=payload.status,
        note=payload.note,
    )


@router.get("/admin/agencies")
async def admin_agencies(_: AdminUser, settings: SettingsDep):
    return await SupabaseRepository(settings).list_agencies()


@router.post("/admin/agencies/{agency_id}/members")
async def add_agency_member(
    agency_id: UUID,
    payload: AgencyMemberRequest,
    _: AdminUser,
    settings: SettingsDep,
):
    try:
        return await SupabaseRepository(settings).add_agency_member(
            agency_id=agency_id,
            user_id=payload.user_id,
            member_role=payload.member_role,
        )
    except ExternalServiceError as exc:
        raise HTTPException(status_code=400, detail="No se pudo vincular la cuenta") from exc


@router.post("/admin/agencies/{agency_id}/accounts")
async def create_agency_account(
    agency_id: UUID,
    payload: AgencyAccountRequest,
    _: AdminUser,
    settings: SettingsDep,
):
    try:
        account = await SupabaseAuthService(settings).create_agency_user(
            email=payload.email.strip().lower(), password=payload.password
        )
        membership = await SupabaseRepository(settings).add_agency_member(
            agency_id=agency_id,
            user_id=account.id,
            member_role=payload.member_role,
        )
        return {
            "user_id": str(account.id),
            "email": account.email,
            "agency_id": str(agency_id),
            "member_role": membership["member_role"],
        }
    except (ExternalServiceError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="No se pudo crear la cuenta. Verifica el correo y que no exista previamente.",
        ) from exc

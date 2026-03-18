from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.controllers.ats_controller import ATSController
from app.models.schemas import ATSCheckRequest, KeywordGapRequest, RegisteredUser, ResumeOptimizeRequest
from app.services.ats_service import GeminiUnavailableError, ScanLimitExceededError
from app.services.auth_dependency import get_current_user

router = APIRouter(prefix="/api/v1", tags=["Talent Probe"])
controller = ATSController()


@router.get("/health")
def health_check():
    return controller.health()


@router.get("/ats/usage")
def ats_usage(current_user: RegisteredUser = Depends(get_current_user)):
    return controller.get_ats_usage(current_user)


@router.get("/ats/history")
def ats_history(current_user: RegisteredUser = Depends(get_current_user)):
    return controller.list_ats_history(current_user)


@router.delete("/ats/history/{scan_id}")
def delete_ats_history_item(scan_id: int, current_user: RegisteredUser = Depends(get_current_user)):
    try:
        return controller.delete_ats_history_item(current_user, scan_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/ats/check")
def ats_check(payload: ATSCheckRequest, current_user: RegisteredUser = Depends(get_current_user)):
    try:
        return controller.check_ats(current_user, payload)
    except ScanLimitExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except GeminiUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/resume/optimize")
def resume_optimize(payload: ResumeOptimizeRequest, _: RegisteredUser = Depends(get_current_user)):
    return controller.optimize_resume(payload)


@router.post("/resume/keyword-gap")
def resume_keyword_gap(payload: KeywordGapRequest, _: RegisteredUser = Depends(get_current_user)):
    return controller.keyword_gap(payload)


@router.post("/resume/extract-text")
async def resume_extract_text(
    file: UploadFile = File(...),
    _: RegisteredUser = Depends(get_current_user),
):
    try:
        return await controller.extract_resume_text(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

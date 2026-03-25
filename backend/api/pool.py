from fastapi import APIRouter
router = APIRouter(tags=["pool"])

@router.get("/pool/status", status_code=501)
def pool_status():
    return {"detail": "Not implemented (Phase 3)"}

from fastapi import APIRouter
router = APIRouter(tags=["submit"])

@router.get("/submit/queue", status_code=501)
def get_queue():
    return {"detail": "Not implemented (Phase 2)"}

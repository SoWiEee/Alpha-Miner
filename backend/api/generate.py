from fastapi import APIRouter
router = APIRouter(tags=["generate"])

@router.post("/generate/mutate", status_code=501)
def mutate():
    return {"detail": "Not implemented yet"}

@router.get("/generate/runs", status_code=501)
def list_runs():
    return {"detail": "Not implemented yet"}

@router.post("/generate/llm", status_code=501)
def generate_llm():
    return {"detail": "Not implemented (Phase 4)"}

@router.post("/generate/gp", status_code=501)
def generate_gp():
    return {"detail": "Not implemented (Phase 5)"}

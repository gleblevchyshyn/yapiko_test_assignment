from fastapi import APIRouter

from .schemas import ParseRequest, ParseResponse

router = APIRouter()

@router.post("/parse", response_model=ParseResponse)
async def parse(request: ParseRequest) -> ParseResponse:
    return ParseResponse(total_uah=0, needs_clarification=True)


@router.get("/health")
async def health():
    return {"status": "ok"}
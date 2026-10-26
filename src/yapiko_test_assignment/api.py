import logging

from fastapi import APIRouter, Request, Response

from .llm import llm_call
from .rules import build_response
from .schemas import LLMOutput, ParseRequest, ParseResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/parse")
async def parse(
    body: ParseRequest, request: Request, response: Response
) -> ParseResponse:
    state = request.app.state

    try:
        llm_result, usage = await llm_call(
            client=state.client,
            system_prompt=state.system_prompt,
            settings=state.settings,
            user_input=body.message,
            output_model=LLMOutput,
        )
    except Exception:
        logger.exception("LLM call failed, falling back to operator")
        response.headers["X-LLM-Fallback"] = "true"
        return ParseResponse(total_uah=0, needs_clarification=True)

    result = build_response(llm_result, state.menu, state.stop_list.get())

    if usage is not None:
        response.headers["X-Prompt-Tokens"] = str(usage.prompt_tokens)
        response.headers["X-Completion-Tokens"] = str(usage.completion_tokens)
        cost = getattr(usage, "cost", None)
        if cost is not None:
            response.headers["X-Cost-USD"] = str(cost)

    return result


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

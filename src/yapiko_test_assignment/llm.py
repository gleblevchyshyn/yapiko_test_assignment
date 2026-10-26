from pydantic import BaseModel
from instructor import AsyncInstructor
from openai.types import CompletionUsage

from .config import Settings


async def llm_call[ResponseModel: BaseModel](*, client: AsyncInstructor, system_prompt: str, settings: Settings,  user_input: str, output_model: type[ResponseModel]) -> tuple[ResponseModel, CompletionUsage | None]:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"<customer_message>\n{user_input}\n</customer_message>"}
    ]
    
    result, completion = await client.chat.completions.create_with_completion(
        model=settings.model,
        messages=messages,
        response_model=output_model,
        max_retries=settings.max_retries,
        temperature=settings.temperature,
    )
    
    return result, completion.usage
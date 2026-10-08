from openai import AsyncOpenAI, AuthenticationError, PermissionDeniedError
from ..config import conf, normalize_api_key
from ..errors import QueryError

async def generate_ai_comment(stats_text):
    if not conf.ai_comment_enabled:
        return ''
    async with AsyncOpenAI(base_url=conf.majsoul_ai_api_base or None,
                           api_key=normalize_api_key(conf.majsoul_ai_api_key), timeout=conf.majsoul_ai_timeout) as client:
        try:
            response = await client.chat.completions.create(
                model=conf.majsoul_ai_model,
                messages=[{'role': 'system', 'content': conf.majsoul_ai_prompt.strip()},
                          {'role': 'user', 'content': stats_text}],
                max_tokens=1000)
        except (AuthenticationError, PermissionDeniedError) as exc:
            raise QueryError('AI 服务拒绝认证或授权，请管理员检查 AI Key、接口地址及模型访问权限。') from exc
        return response.choices[0].message.content or ''

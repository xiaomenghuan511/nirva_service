import datetime
import uuid
from typing import List, cast

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger

import nirva_service.db.redis_user
import nirva_service.prompts.builtin as builtin_prompt
from nirva_service.models import (
    ChatActionRequest,
    ChatActionResponse,
    ChatMessage,
    MessageRole,
)
from nirva_service.services.langgraph_services.langgraph_models import (
    RequestTaskMessageListType,
)
from nirva_service.services.langgraph_services.langgraph_request_task import (
    LanggraphRequestTask,
)

from .app_service_server import AppserviceServerInstance
from .oauth_user import get_authenticated_user

###################################################################################################################################################################
chat_action_router = APIRouter()


###################################################################################################################################################################
def _assemble_chat_messages(
    chat_history: List[ChatMessage],
) -> RequestTaskMessageListType:
    ret_messages: RequestTaskMessageListType = []
    for msg in chat_history:
        if msg.role == MessageRole.SYSTEM:
            ret_messages.append(SystemMessage(content=msg.content))
        elif msg.role == MessageRole.HUMAN:
            ret_messages.append(HumanMessage(content=msg.content))
        elif msg.role == MessageRole.AI:
            ret_messages.append(AIMessage(content=msg.content))
        # else:
        #     logger.warning(f"Unknown message role: {msg.role}")

    return ret_messages


###################################################################################################################################################################
###################################################################################################################################################################
###################################################################################################################################################################
@chat_action_router.post(path="/action/chat/v1/", response_model=ChatActionResponse)
async def handle_chat_action(
    request_data: ChatActionRequest,
    appservice_server: AppserviceServerInstance,
    authenticated_user: str = Depends(get_authenticated_user),
) -> ChatActionResponse:
    logger.info(f"/action/chat/v1/: {request_data.model_dump_json()}")

    try:
        # 检查内容。
        if len(request_data.human_message.content.strip()) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请求内容不能为空",
            )

        # 检查用户是否已认证。
        display_name = nirva_service.db.redis_user.get_user_display_name(
            username=authenticated_user
        )
        assert (
            display_name != ""
        ), f"用户 {authenticated_user} 的显示名称不能为空，请先设置显示名称。"

        # 测试的返回。
        is_test_return = False
        if is_test_return:
            # 直接将用户说的话返回给客户端
            return ChatActionResponse(
                ai_message=ChatMessage(
                    id=str(uuid.uuid4()),
                    role=MessageRole.AI,
                    content=request_data.human_message.content,
                    time_stamp=datetime.datetime.now().isoformat(),
                ),
            )

        # 构建提示词。
        prompt = builtin_prompt.user_session_chat_message(
            username=authenticated_user,
            display_name=display_name,
            content=request_data.human_message.content,
            date_time=request_data.human_message.time_stamp,
        )

        # 系统提示词。
        system_message = SystemMessage(
            content=builtin_prompt.user_session_system_message(
                authenticated_user,
                display_name,
            )
        )

        # 构建对话历史
        chat_history = _assemble_chat_messages(request_data.chat_history)

        # 构建请求任务
        # 后续如果面临 chat_history 特别大的情况，可以开新的api，将 chat_history 分批处理，缓存到redis中, 加超时机制。这样可以减小客户端上传的负担。
        # 目前先不做，太早了。再一个，本身LLM的上下文窗口就有限制，chat_history即使能传输很大，也不一定能处理。
        # 目前策略: 服务器不存客户端的任何对话历史，客户端只上传当前对话的内容和历史。
        request_task = LanggraphRequestTask(
            username=authenticated_user,
            prompt=prompt,
            chat_history=cast(
                RequestTaskMessageListType,
                [system_message] + chat_history,
            ),
        )

        # 处理请求
        appservice_server.langgraph_service.chat(request_handlers=[request_task])
        if len(request_task._response.messages) == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="处理请求时未返回内容",
            )

        # 检查最后一条消息是否为 AI 消息
        if request_task._response.messages[-1].type != "ai":
            logger.error(
                f"处理请求时最后一条消息不是 AI 消息: {request_task._response.messages[-1]}"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="处理请求时最后一条消息不是 AI 消息",
            )

        # 打印聊天记录
        for msg in (
            [system_message]
            + chat_history
            + [HumanMessage(content=prompt)]
            + request_task._response.messages
        ):
            logger.info(msg.content)

        # 返回响应
        return ChatActionResponse(
            ai_message=ChatMessage(
                id=str(uuid.uuid4()),
                role=MessageRole.AI,  # AI消息
                content=request_task.last_response_message_content,
                time_stamp=datetime.datetime.now().isoformat(),
            ),
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"处理请求失败: {e}",
        )


###################################################################################################################################################################
###################################################################################################################################################################
###################################################################################################################################################################

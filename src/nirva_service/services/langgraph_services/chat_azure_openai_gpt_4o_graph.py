import os

# import sys
import traceback

# from pathlib import Path
from typing import Annotated, Dict, List

from langchain.schema import HumanMessage
from langchain_core.messages import BaseMessage
from langchain_openai import AzureChatOpenAI
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from pydantic import SecretStr
from typing_extensions import TypedDict


############################################################################################################
class State(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]


############################################################################################################
def create_compiled_stage_graph(
    node_name: str, temperature: float
) -> CompiledStateGraph:
    assert node_name != "", "node_name is empty"

    llm = AzureChatOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=SecretStr(str(os.getenv("AZURE_OPENAI_API_KEY"))),
        azure_deployment="gpt-4o",
        api_version="2024-02-01",
        temperature=temperature,
    )

    def invoke_azure_chat_openai_llm_action(
        state: State,
    ) -> Dict[str, List[BaseMessage]]:
        try:
            return {"messages": [llm.invoke(state["messages"])]}
        except Exception as e:
            # 1) 打印异常信息本身
            print(f"invoke_azure_chat_openai_llm_action, An error occurred: {e}")

            # 2) 打印完整堆栈信息，方便进一步排查
            traceback.print_exc()

            # 当出现 Azure 内容过滤的情况，或者其他类型异常时，视需求可在此返回空字符串或者自定义提示。
            # return {"messages": [AIMessage(content="")]}
            raise e

    graph_builder = StateGraph(State)
    graph_builder.add_node(node_name, invoke_azure_chat_openai_llm_action)
    graph_builder.set_entry_point(node_name)
    graph_builder.set_finish_point(node_name)
    return graph_builder.compile()


############################################################################################################
def stream_graph_updates(
    state_compiled_graph: CompiledStateGraph,
    chat_history_state: State,
    user_input_state: State,
) -> List[BaseMessage]:
    ret: List[BaseMessage] = []

    merged_message_context = {
        "messages": chat_history_state["messages"] + user_input_state["messages"]
    }

    for event in state_compiled_graph.stream(merged_message_context):
        for value in event.values():
            # ai_messages: List[AIMessage] = cast(List[AIMessage], value["messages"])
            # print("Assistant:", ai_messages[-1].content)
            ret.extend(value["messages"])

    return ret


############################################################################################################
def main() -> None:
    # 聊天历史
    chat_history_state: State = {"messages": []}

    # 生成聊天机器人状态图
    compiled_stage_graph = create_compiled_stage_graph(
        "azure_chat_openai_chatbot_node", 0.7
    )

    while True:
        try:
            user_input = input("User: ")
            if user_input.lower() in ["quit", "exit", "q"]:
                print("Goodbye!")
                break

            # 用户输入
            user_input_state: State = {"messages": [HumanMessage(content=user_input)]}

            # 获取回复
            update_messages = stream_graph_updates(
                state_compiled_graph=compiled_stage_graph,
                chat_history_state=chat_history_state,
                user_input_state=user_input_state,
            )

            # 测试用：记录上下文。
            chat_history_state["messages"].extend(user_input_state["messages"])
            chat_history_state["messages"].extend(update_messages)

        except Exception as e:
            assert False, f"Error in processing user input = {e}"
            # break


############################################################################################################
if __name__ == "__main__":
    # 运行主函数 == 测试。
    main()

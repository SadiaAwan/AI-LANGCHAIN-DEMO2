import asyncio
import re
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.tools import Tool

from util.models import get_model
from util.streaming_utils import STREAM_MODES, handle_stream_async
from util.pretty_print import print_mcp_tools, get_user_input


# -------------------------------
# Middleware + Input Parser
# -------------------------------
def wrap_tool(tool):
    async def wrapped_func(*args, **kwargs):

        # -------------------------------
        # FIX: hantera fel input från agent (string → JSON)
        # -------------------------------
        if args and isinstance(args[0], str):
            text_input = args[0]

            # ADDITION: "7+3"
            match_add = re.match(r"(\d+)\s*\+\s*(\d+)", text_input)
            if match_add and tool.name == "add_numbers":
                a = int(match_add.group(1))
                b = int(match_add.group(2))
                result = await tool.ainvoke({"a": a, "b": b})

            # TEXT TOOLS
            elif tool.name in ["count_words", "to_uppercase"]:
                result = await tool.ainvoke({"text": text_input})

            else:
                result = await tool.ainvoke(text_input)

        else:
            result = await tool.ainvoke(*args, **kwargs)

        # -------------------------------
        # Middleware (modifiera output)
        # -------------------------------
        if isinstance(result, int):
            return f"Resultatet är: {result}"
        elif isinstance(result, str):
            return f"Bearbetad text: {result}"

        return result

    return Tool(
        name=tool.name,
        description=tool.description,
        func=lambda *args, **kwargs: asyncio.run(wrapped_func(*args, **kwargs)),
        coroutine=wrapped_func,
    )


async def run_async():
    # -------------------------------
    # Modell
    # -------------------------------
    model = get_model()

    # -------------------------------
    # MCP client
    # -------------------------------
    mcp_client = MultiServerMCPClient({
        "my_tools": {
            "transport": "streamable_http",
            "url": "http://localhost:8003/mcp",
        }
    })

    # -------------------------------
    # Hämta tools
    # -------------------------------
    tools = await mcp_client.get_tools()

    print("\nALLA TOOLS:")
    print_mcp_tools(tools)

    # -------------------------------
    # FILTRERA TOOLS (krav)
    # -------------------------------
    allowed_tool_names = [
        "count_words",
        "add_numbers",
        "to_uppercase"
    ]

    filtered_tools = [
        t for t in tools if t.name in allowed_tool_names
    ]

    print("\nFILTRERADE TOOLS:")
    print_mcp_tools(filtered_tools)

    # -------------------------------
    # Middleware (wrap tools)
    # -------------------------------
    wrapped_tools = [
        wrap_tool(t) for t in filtered_tools
    ]

    # -------------------------------
    # Skapa agent
    # -------------------------------
    agent = create_agent(
        model=model,
        tools=wrapped_tools,
        system_prompt=(
            "Du är en hjälpsam AI-assistent.\n"
            "Du använder verktyg när det behövs.\n"
            "Om användaren skriver matematik som 7+3 ska du använda rätt verktyg.\n"
            "Alla svar ska vara på svenska.\n"
            "Var tydlig och kortfattad."
        ),
    )

    # -------------------------------
    # User input
    # -------------------------------
    user_input = get_user_input("Ställ en fråga")

    # -------------------------------
    # Kör agent
    # -------------------------------
    process_stream = agent.astream(
        {"messages": [{"role": "user", "content": user_input}]},
        stream_mode=STREAM_MODES,
    )

    await handle_stream_async(process_stream)


def run():
    asyncio.run(run_async())


if __name__ == "__main__":
    run()
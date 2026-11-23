import sys
import os
import asyncio
from contextlib import asynccontextmanager
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class FinancialMCPClient:
    def __init__(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        self.server_script = os.path.join(project_root, "servers", "financial_server.py")
        self.python_exe = sys.executable

    @asynccontextmanager
    async def connect(self):
        """Quản lý kết nối đến Server."""
        if not os.path.exists(self.server_script):
            raise FileNotFoundError(f"Không tìm thấy file server tại: {self.server_script}")

        server_params = StdioServerParameters(
            command=self.python_exe,
            args=[self.server_script],
            env=os.environ.copy()
        )

        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
        except Exception as e:
            print(f"❌ LỖI KẾT NỐI MCP SERVER: {e}", file=sys.stderr)
            raise e

    async def call_tool(self, tool_name: str, args: dict, timeout: int = 1200) -> str:
        async def _execute_tool():
            async with self.connect() as session:
                result = await session.call_tool(tool_name, arguments=args)
                
                if result.content and hasattr(result.content[0], "text"):
                    return result.content[0].text
                return str(result)

        try:
            return await asyncio.wait_for(_execute_tool(), timeout=timeout)
                    
        except asyncio.TimeoutError:
            return f"⚠️ Timeout: Server xử lý '{tool_name}' quá lâu (>{timeout}s)."
        except Exception as e:
            return f"❌ Lỗi gọi Tool '{tool_name}': {str(e)}"
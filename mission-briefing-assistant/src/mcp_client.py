"""
MCP Client
==========
Client for connecting to MCP servers via stdio and invoking tools.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource

logger = logging.getLogger(__name__)


class MCPClient:
    """Client for interacting with a single MCP server."""
    
    def __init__(self, name: str, server_process):
        self.name = name
        self.server_process = server_process
        self.session: Optional[ClientSession] = None
        self.read = None
        self.write = None
        self.tools: List[Tool] = []
        self.resources: List[Dict] = []
        self._client_context = None
        
    async def connect(self) -> bool:
        """Connect to the MCP server."""
        try:
            logger.info(f"Connecting to MCP server: {self.name}")
            
            # Create stdio client using the existing process's stdin/stdout
            self._client_context = stdio_client(
                StdioServerParameters(
                    command=self.server_process.command,
                    args=self.server_process.args,
                    env=None
                )
            )
            
            # This creates a new process - we'll use it for communication
            self.read, self.write = await self._client_context.__aenter__()
            
            # Create session
            self.session = ClientSession(self.read, self.write)
            await self.session.__aenter__()
            
            # Initialize the session
            result = await self.session.initialize()
            logger.info(f"Connected to {self.name}: {result.server_info.name} v{result.server_info.version}")
            
            # List available tools
            await self.refresh_capabilities()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to {self.name}: {e}", exc_info=True)
            return False
    
    async def refresh_capabilities(self):
        """Refresh the list of available tools and resources."""
        try:
            # List tools
            tools_result = await self.session.list_tools()
            self.tools = tools_result.tools
            logger.info(f"Server {self.name} has {len(self.tools)} tools: {[t.name for t in self.tools]}")
            
            # List resources if available
            try:
                resources_result = await self.session.list_resources()
                self.resources = [
                    {"uri": r.uri, "name": r.name, "mimeType": r.mimeType}
                    for r in resources_result.resources
                ]
                logger.info(f"Server {self.name} has {len(self.resources)} resources")
            except Exception as e:
                logger.debug(f"Server {self.name} does not support resources: {e}")
                self.resources = []
                
        except Exception as e:
            logger.error(f"Failed to refresh capabilities for {self.name}: {e}")
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on the MCP server."""
        if not self.session:
            raise RuntimeError(f"Not connected to {self.name}")
        
        logger.info(f"Calling tool {tool_name} on {self.name} with args: {arguments}")
        
        try:
            result = await self.session.call_tool(tool_name, arguments)
            
            # Parse the result
            output = {
                "tool": tool_name,
                "server": self.name,
                "success": not result.isError if hasattr(result, 'isError') else True,
                "content": []
            }
            
            # Extract content
            for content_item in result.content:
                if isinstance(content_item, TextContent):
                    output["content"].append({
                        "type": "text",
                        "text": content_item.text
                    })
                elif isinstance(content_item, ImageContent):
                    output["content"].append({
                        "type": "image",
                        "data": content_item.data,
                        "mimeType": content_item.mimeType
                    })
                elif isinstance(content_item, EmbeddedResource):
                    output["content"].append({
                        "type": "resource",
                        "uri": content_item.resource.uri if hasattr(content_item.resource, 'uri') else None
                    })
                else:
                    output["content"].append({
                        "type": "unknown",
                        "data": str(content_item)
                    })
            
            logger.debug(f"Tool {tool_name} returned {len(output['content'])} content items")
            return output
            
        except Exception as e:
            logger.error(f"Error calling tool {tool_name}: {e}", exc_info=True)
            return {
                "tool": tool_name,
                "server": self.name,
                "success": False,
                "error": str(e),
                "content": []
            }
    
    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read a resource from the MCP server."""
        if not self.session:
            raise RuntimeError(f"Not connected to {self.name}")
        
        logger.info(f"Reading resource {uri} from {self.name}")
        
        try:
            result = await self.session.read_resource(uri)
            
            output = {
                "uri": uri,
                "server": self.name,
                "success": True,
                "contents": []
            }
            
            for content in result.contents:
                if hasattr(content, 'text'):
                    output["contents"].append({
                        "type": "text",
                        "text": content.text,
                        "uri": content.uri if hasattr(content, 'uri') else uri
                    })
                elif hasattr(content, 'blob'):
                    output["contents"].append({
                        "type": "blob",
                        "data": content.blob,
                        "uri": content.uri if hasattr(content, 'uri') else uri
                    })
            
            return output
            
        except Exception as e:
            logger.error(f"Error reading resource {uri}: {e}", exc_info=True)
            return {
                "uri": uri,
                "server": self.name,
                "success": False,
                "error": str(e),
                "contents": []
            }
    
    def get_tools(self) -> List[Tool]:
        """Get list of available tools."""
        return self.tools
    
    def get_resources(self) -> List[Dict]:
        """Get list of available resources."""
        return self.resources
    
    async def disconnect(self):
        """Disconnect from the MCP server."""
        try:
            if self.session:
                await self.session.__aexit__(None, None, None)
            if self._client_context:
                await self._client_context.__aexit__(None, None, None)
            logger.info(f"Disconnected from {self.name}")
        except Exception as e:
            logger.error(f"Error disconnecting from {self.name}: {e}")


class MCPClientManager:
    """Manages connections to multiple MCP servers."""
    
    def __init__(self, server_manager):
        self.server_manager = server_manager
        self.clients: Dict[str, MCPClient] = {}
    
    async def connect_all(self) -> Dict[str, bool]:
        """Connect to all running MCP servers."""
        results = {}
        
        for server_name in self.server_manager.get_running_servers():
            server = self.server_manager.get_server(server_name)
            if server and server.is_running():
                client = MCPClient(server_name, server)
                success = await client.connect()
                
                if success:
                    self.clients[server_name] = client
                
                results[server_name] = success
        
        return results
    
    async def disconnect_all(self):
        """Disconnect from all MCP servers."""
        for client in self.clients.values():
            await client.disconnect()
        self.clients.clear()
    
    def get_client(self, server_name: str) -> Optional[MCPClient]:
        """Get a client by server name."""
        return self.clients.get(server_name)
    
    def list_clients(self) -> List[str]:
        """List all connected clients."""
        return list(self.clients.keys())
    
    def get_all_tools(self) -> Dict[str, List[Tool]]:
        """Get all tools from all connected servers."""
        all_tools = {}
        for name, client in self.clients.items():
            all_tools[name] = client.get_tools()
        return all_tools
    
    async def __aenter__(self):
        """Context manager entry."""
        await self.connect_all()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.disconnect_all()


async def main():
    """Test the MCP client."""
    import yaml
    from pathlib import Path
    from mcp_server_manager import MCPServerManager
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load config
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    # Start servers
    server_manager = MCPServerManager(config)
    await server_manager.start_all()
    
    # Give servers time to start
    await asyncio.sleep(2)
    
    # Connect clients
    client_manager = MCPClientManager(server_manager)
    await client_manager.connect_all()
    
    print("\n=== Connected Clients ===")
    for name in client_manager.list_clients():
        print(f"✓ {name}")
    
    print("\n=== Available Tools ===")
    all_tools = client_manager.get_all_tools()
    for server_name, tools in all_tools.items():
        print(f"\n{server_name}:")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")
    
    # Test a tool call if filesystem is available
    if 'filesystem' in client_manager.list_clients():
        print("\n=== Testing Tool Call ===")
        client = client_manager.get_client('filesystem')
        result = await client.call_tool('list_directory', {'path': '.'})
        print(f"Result: {json.dumps(result, indent=2)}")
    
    # Cleanup
    await client_manager.disconnect_all()
    await server_manager.stop_all()
    print("\nDone")


if __name__ == "__main__":
    asyncio.run(main())

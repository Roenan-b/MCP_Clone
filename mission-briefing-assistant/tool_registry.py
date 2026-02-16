"""
Tool Registry
=============
Unified interface for accessing tools across multiple MCP servers.
"""

import logging
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry providing unified access to tools across MCP servers."""
    
    def __init__(self, client_manager):
        self.client_manager = client_manager
        self.tool_map: Dict[str, tuple] = {}  # tool_name -> (server_name, tool_schema)
        self._refresh()
    
    def _refresh(self):
        """Refresh the tool registry from connected clients."""
        self.tool_map.clear()
        
        all_tools = self.client_manager.get_all_tools()
        
        for server_name, tools in all_tools.items():
            for tool in tools:
                # Create a unique tool name with server prefix
                full_tool_name = f"{server_name}.{tool.name}"
                self.tool_map[full_tool_name] = (server_name, tool)
                
                # Also add without prefix if it doesn't conflict
                if tool.name not in self.tool_map:
                    self.tool_map[tool.name] = (server_name, tool)
                
                logger.debug(f"Registered tool: {full_tool_name}")
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """List all available tools with their schemas."""
        tools = []
        
        for tool_name, (server_name, tool_schema) in self.tool_map.items():
            # Skip fully-qualified names (server.tool) in listing
            if '.' in tool_name:
                continue
                
            tools.append({
                "name": tool_name,
                "server": server_name,
                "description": tool_schema.description,
                "input_schema": tool_schema.inputSchema if hasattr(tool_schema, 'inputSchema') else {}
            })
        
        return tools
    
    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get the schema for a specific tool."""
        if tool_name not in self.tool_map:
            return None
        
        server_name, tool_schema = self.tool_map[tool_name]
        
        return {
            "name": tool_name,
            "server": server_name,
            "description": tool_schema.description,
            "input_schema": tool_schema.inputSchema if hasattr(tool_schema, 'inputSchema') else {}
        }
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool by name with arguments."""
        if tool_name not in self.tool_map:
            raise ValueError(f"Tool '{tool_name}' not found in registry")
        
        server_name, tool_schema = self.tool_map[tool_name]
        actual_tool_name = tool_schema.name
        
        client = self.client_manager.get_client(server_name)
        if not client:
            raise RuntimeError(f"Client for server '{server_name}' not found")
        
        logger.info(f"Calling tool: {tool_name} (server: {server_name}, actual: {actual_tool_name})")
        
        return await client.call_tool(actual_tool_name, arguments)
    
    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """
        Get tools formatted for LLM tool use.
        Returns tools in Anthropic's tool use format.
        """
        tools = []
        
        for tool_name, (server_name, tool_schema) in self.tool_map.items():
            # Skip fully-qualified names
            if '.' in tool_name:
                continue
            
            tool_def = {
                "name": tool_name,
                "description": tool_schema.description or f"Tool from {server_name} server"
            }
            
            # Add input schema if available
            if hasattr(tool_schema, 'inputSchema') and tool_schema.inputSchema:
                tool_def["input_schema"] = tool_schema.inputSchema
            else:
                # Provide a minimal schema
                tool_def["input_schema"] = {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            
            tools.append(tool_def)
        
        return tools
    
    # Convenience methods for common operations
    
    async def read_file(self, path: str) -> Optional[str]:
        """Read a file using the filesystem tool."""
        try:
            result = await self.call_tool('read_file', {'path': path})
            
            if result.get('success') and result.get('content'):
                for content_item in result['content']:
                    if content_item.get('type') == 'text':
                        return content_item.get('text')
            
            return None
            
        except Exception as e:
            logger.error(f"Error reading file {path}: {e}")
            return None
    
    async def list_directory(self, path: str = '.') -> Optional[List[str]]:
        """List directory contents using the filesystem tool."""
        try:
            result = await self.call_tool('list_directory', {'path': path})
            
            if result.get('success') and result.get('content'):
                for content_item in result['content']:
                    if content_item.get('type') == 'text':
                        # Parse the directory listing
                        text = content_item.get('text', '')
                        # This is simplified - actual parsing depends on server format
                        return [line.strip() for line in text.split('\n') if line.strip()]
            
            return None
            
        except Exception as e:
            logger.error(f"Error listing directory {path}: {e}")
            return None
    
    async def search_files(self, path: str, pattern: str) -> Optional[List[str]]:
        """Search for files using the filesystem tool."""
        try:
            result = await self.call_tool('search_files', {
                'path': path,
                'pattern': pattern
            })
            
            if result.get('success') and result.get('content'):
                for content_item in result['content']:
                    if content_item.get('type') == 'text':
                        text = content_item.get('text', '')
                        return [line.strip() for line in text.split('\n') if line.strip()]
            
            return None
            
        except Exception as e:
            logger.error(f"Error searching files: {e}")
            return None
    
    async def execute_query(self, sql: str, db_path: Optional[str] = None) -> Optional[Any]:
        """Execute a SQL query using the sqlite tool."""
        try:
            args = {'query': sql}
            if db_path:
                args['db_path'] = db_path
            
            result = await self.call_tool('execute_query', args)
            
            if result.get('success') and result.get('content'):
                for content_item in result['content']:
                    if content_item.get('type') == 'text':
                        return content_item.get('text')
            
            return None
            
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            return None
    
    async def git_log(self, repo_path: Optional[str] = None, max_count: int = 10) -> Optional[str]:
        """Get git log using the git tool."""
        try:
            args = {'max_count': max_count}
            if repo_path:
                args['repo_path'] = repo_path
            
            result = await self.call_tool('git_log', args)
            
            if result.get('success') and result.get('content'):
                for content_item in result['content']:
                    if content_item.get('type') == 'text':
                        return content_item.get('text')
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting git log: {e}")
            return None
    
    async def git_show(self, ref: str, repo_path: Optional[str] = None) -> Optional[str]:
        """Show git object using the git tool."""
        try:
            args = {'ref': ref}
            if repo_path:
                args['repo_path'] = repo_path
            
            result = await self.call_tool('git_show', args)
            
            if result.get('success') and result.get('content'):
                for content_item in result['content']:
                    if content_item.get('type') == 'text':
                        return content_item.get('text')
            
            return None
            
        except Exception as e:
            logger.error(f"Error showing git object: {e}")
            return None


async def main():
    """Test the tool registry."""
    import asyncio
    import yaml
    from pathlib import Path
    from mcp_server_manager import MCPServerManager
    from mcp_client import MCPClientManager
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load config
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    # Start servers and connect clients
    server_manager = MCPServerManager(config)
    await server_manager.start_all()
    await asyncio.sleep(2)
    
    client_manager = MCPClientManager(server_manager)
    await client_manager.connect_all()
    
    # Create tool registry
    registry = ToolRegistry(client_manager)
    
    print("\n=== Available Tools ===")
    tools = registry.list_tools()
    for tool in tools:
        print(f"\n{tool['name']} ({tool['server']})")
        print(f"  {tool['description']}")
    
    print("\n=== Tools for LLM ===")
    llm_tools = registry.get_tools_for_llm()
    print(f"Total tools: {len(llm_tools)}")
    for tool in llm_tools:
        print(f"  - {tool['name']}")
    
    # Cleanup
    await client_manager.disconnect_all()
    await server_manager.stop_all()
    print("\nDone")


if __name__ == "__main__":
    asyncio.run(main())

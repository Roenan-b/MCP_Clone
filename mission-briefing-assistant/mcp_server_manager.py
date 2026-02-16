"""
MCP Server Manager
==================
Manages lifecycle of MCP servers as subprocesses, communicating via stdio.
"""

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class MCPServer:
    """Represents a single MCP server instance."""
    
    def __init__(self, name: str, command: str, args: List[str], working_dir: str = "."):
        self.name = name
        self.command = command
        self.args = args
        self.working_dir = Path(working_dir).resolve()
        self.process: Optional[asyncio.subprocess.Process] = None
        self.running = False
        
    async def start(self) -> bool:
        """Start the MCP server as a subprocess."""
        if self.running:
            logger.warning(f"Server {self.name} is already running")
            return True
            
        try:
            logger.info(f"Starting MCP server: {self.name}")
            logger.debug(f"Command: {self.command} {' '.join(self.args)}")
            logger.debug(f"Working directory: {self.working_dir}")
            
            # Start the process with stdio pipes
            self.process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.working_dir)
            )
            
            self.running = True
            logger.info(f"Server {self.name} started successfully (PID: {self.process.pid})")
            
            # Start monitoring stderr in background
            asyncio.create_task(self._monitor_stderr())
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start server {self.name}: {e}")
            self.running = False
            return False
    
    async def _monitor_stderr(self):
        """Monitor and log stderr output from the server."""
        if not self.process or not self.process.stderr:
            return
            
        try:
            async for line in self.process.stderr:
                decoded = line.decode('utf-8', errors='ignore').strip()
                if decoded:
                    logger.debug(f"[{self.name} stderr] {decoded}")
        except Exception as e:
            logger.debug(f"Stderr monitoring ended for {self.name}: {e}")
    
    async def stop(self) -> bool:
        """Stop the MCP server."""
        if not self.running or not self.process:
            logger.warning(f"Server {self.name} is not running")
            return True
            
        try:
            logger.info(f"Stopping MCP server: {self.name}")
            
            # Try graceful shutdown first
            self.process.terminate()
            
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"Server {self.name} did not terminate gracefully, killing...")
                self.process.kill()
                await self.process.wait()
            
            self.running = False
            self.process = None
            logger.info(f"Server {self.name} stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping server {self.name}: {e}")
            return False
    
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self.running and self.process is not None and self.process.returncode is None


class MCPServerManager:
    """Manages multiple MCP servers."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.servers: Dict[str, MCPServer] = {}
        self._initialize_servers()
    
    def _initialize_servers(self):
        """Initialize server instances from config."""
        server_configs = self.config.get('mcp_servers', {})
        
        for name, server_config in server_configs.items():
            if not server_config.get('enabled', False):
                logger.info(f"Server {name} is disabled in config")
                continue
                
            server = MCPServer(
                name=name,
                command=server_config['command'],
                args=server_config['args'],
                working_dir=server_config.get('working_dir', '.')
            )
            self.servers[name] = server
            logger.info(f"Initialized server configuration: {name}")
    
    async def start_all(self) -> Dict[str, bool]:
        """Start all configured servers."""
        results = {}
        
        for name, server in self.servers.items():
            results[name] = await server.start()
            # Give server a moment to initialize
            await asyncio.sleep(0.5)
        
        return results
    
    async def stop_all(self) -> Dict[str, bool]:
        """Stop all running servers."""
        results = {}
        
        for name, server in self.servers.items():
            results[name] = await server.stop()
        
        return results
    
    async def start_server(self, name: str) -> bool:
        """Start a specific server by name."""
        if name not in self.servers:
            logger.error(f"Server {name} not found in configuration")
            return False
        
        return await self.servers[name].start()
    
    async def stop_server(self, name: str) -> bool:
        """Stop a specific server by name."""
        if name not in self.servers:
            logger.error(f"Server {name} not found in configuration")
            return False
        
        return await self.servers[name].stop()
    
    def get_server(self, name: str) -> Optional[MCPServer]:
        """Get a server instance by name."""
        return self.servers.get(name)
    
    def list_servers(self) -> List[str]:
        """List all configured server names."""
        return list(self.servers.keys())
    
    def get_running_servers(self) -> List[str]:
        """Get list of currently running servers."""
        return [name for name, server in self.servers.items() if server.is_running()]
    
    async def __aenter__(self):
        """Context manager entry."""
        await self.start_all()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.stop_all()


async def main():
    """Test the server manager."""
    import yaml
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load config
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    # Create manager
    manager = MCPServerManager(config)
    
    print("\n=== Starting MCP Servers ===")
    results = await manager.start_all()
    
    for name, success in results.items():
        status = "✓" if success else "✗"
        print(f"{status} {name}")
    
    print("\n=== Servers Running ===")
    print(f"Active servers: {', '.join(manager.get_running_servers())}")
    
    print("\nServers will run for 10 seconds...")
    await asyncio.sleep(10)
    
    print("\n=== Stopping MCP Servers ===")
    await manager.stop_all()
    print("Done")


if __name__ == "__main__":
    asyncio.run(main())

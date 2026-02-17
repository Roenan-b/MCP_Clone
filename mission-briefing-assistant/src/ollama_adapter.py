"""Ollama LLM Adapter"""
import json
import logging
import requests
from typing import Any, Dict, List, Optional
from llm_adapter import LLMAdapter

logger = logging.getLogger(__name__)


class OllamaAdapter(LLMAdapter):
    """Adapter for Ollama local models."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model = config.get('model', 'llama3.2:latest')
        self.base_url = config.get('base_url', 'http://localhost:11434')
        self.temperature = config.get('temperature', 0.7)
        
        # Test connection
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
            logger.info(f"✓ Connected to Ollama at {self.base_url}")
            logger.info(f"Using model: {self.model}")
        except Exception as e:
            logger.error(f"Cannot connect to Ollama at {self.base_url}")
            logger.error("Make sure Ollama is running: ollama serve")
            raise
    
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate using Ollama."""
        
        try:
            # Format messages for Ollama
            formatted_messages = []
            
            # Add system prompt
            if system:
                formatted_messages.append({
                    "role": "system",
                    "content": system
                })
            
            # Process conversation messages
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                
                # Handle different content formats
                if isinstance(content, list):
                    # Flatten structured content (tool results, etc.)
                    parts = []
                    for item in content:
                        if item.get("type") == "tool_result":
                            tool_content = item.get("content", "")
                            parts.append(f"[Tool Result]\n{tool_content}")
                        elif item.get("type") == "tool_use":
                            tool_name = item.get("name", "unknown")
                            tool_input = json.dumps(item.get("input", {}), indent=2)
                            parts.append(f"[Using tool: {tool_name}]\nInput: {tool_input}")
                        elif item.get("type") == "text":
                            parts.append(item.get("text", ""))
                    
                    content = "\n".join(parts)
                
                formatted_messages.append({
                    "role": role,
                    "content": str(content)
                })
            
            # Add tool information to system prompt if tools are available
            if tools and formatted_messages:
                tool_instructions = self._format_tools_for_prompt(tools)
                
                # Add to existing system message or create new one
                if formatted_messages[0]["role"] == "system":
                    formatted_messages[0]["content"] += f"\n\n{tool_instructions}"
                else:
                    formatted_messages.insert(0, {
                        "role": "system",
                        "content": tool_instructions
                    })
            
            logger.debug(f"Calling Ollama with {len(formatted_messages)} messages")
            
            # Call Ollama API
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": formatted_messages,
                    "stream": False,
                    "options": {
                        "temperature": kwargs.get('temperature', self.temperature),
                        "num_predict": kwargs.get('max_tokens', 4096)
                    }
                },
                timeout=120  # Give model time to respond
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract response
            response_text = data["message"]["content"]
            
            logger.debug(f"Ollama response length: {len(response_text)} chars")
            
            # Build result structure
            result = {
                "id": f"ollama_{hash(response_text) % 10000:04d}",
                "model": self.model,
                "stop_reason": data.get("done_reason", "stop"),
                "content": [{"type": "text", "text": response_text}],
                "tool_calls": [],
                "usage": {
                    "input_tokens": data.get("prompt_eval_count", 0),
                    "output_tokens": data.get("eval_count", 0)
                }
            }
            
            # Try to extract tool calls from response
            if tools:
                tool_calls = self._extract_tool_calls(response_text, tools)
                result["tool_calls"] = tool_calls
                
                if tool_calls:
                    logger.info(f"Extracted {len(tool_calls)} tool call(s)")
            
            return result
            
        except requests.exceptions.Timeout:
            logger.error("Ollama request timed out - model may be too slow")
            raise
        except requests.exceptions.ConnectionError:
            logger.error("Cannot connect to Ollama - is it running? (ollama serve)")
            raise
        except Exception as e:
            logger.error(f"Ollama error: {e}", exc_info=True)
            raise
    
    def _format_tools_for_prompt(self, tools: List[Dict[str, Any]]) -> str:
        """Format tool definitions for inclusion in prompt."""
        tool_text = "\n## Available Tools\n\n"
        tool_text += "You have access to the following tools. To use a tool, respond with a JSON block:\n"
        tool_text += '```json\n{"tool": "tool_name", "arguments": {...}}\n```\n\n'
        
        for tool in tools:
            tool_text += f"### {tool['name']}\n"
            tool_text += f"{tool['description']}\n"
            
            if tool.get('input_schema'):
                schema = tool['input_schema']
                if schema.get('properties'):
                    tool_text += "Arguments:\n"
                    for prop, details in schema['properties'].items():
                        prop_type = details.get('type', 'string')
                        prop_desc = details.get('description', '')
                        required = prop in schema.get('required', [])
                        req_marker = " (required)" if required else " (optional)"
                        tool_text += f"- {prop} ({prop_type}){req_marker}: {prop_desc}\n"
            
            tool_text += "\n"
        
        return tool_text
    
    def _extract_tool_calls(self, text: str, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract tool calls from model response."""
        tool_calls = []
        
        # Look for JSON blocks with tool calls
        import re
        
        # Pattern 1: ```json ... ```
        json_blocks = re.findall(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        
        # Pattern 2: Plain JSON objects
        if not json_blocks:
            json_blocks = re.findall(r'\{[^\}]*"tool"[^\}]*\}', text, re.DOTALL)
        
        for block in json_blocks:
            try:
                data = json.loads(block)
                
                # Check if it's a tool call
                if 'tool' in data or 'name' in data:
                    tool_name = data.get('tool') or data.get('name')
                    tool_args = data.get('arguments') or data.get('input') or data.get('args') or {}
                    
                    # Verify tool exists
                    if any(t['name'] == tool_name for t in tools):
                        tool_calls.append({
                            "id": f"tool_{hash(block) % 10000:04d}",
                            "name": tool_name,
                            "input": tool_args
                        })
            except json.JSONDecodeError:
                continue
        
        return tool_calls
"""
LLM Adapter
===========
Interface for LLM providers with support for tool use.
"""

import logging
import os
from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod

import anthropic

logger = logging.getLogger(__name__)


class LLMAdapter(ABC):
    """Abstract base class for LLM adapters."""
    
    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate a response from the LLM.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tool definitions
            system: Optional system prompt
            **kwargs: Additional provider-specific parameters
        
        Returns:
            Dict with 'content', 'tool_calls', 'stop_reason', etc.
        """
        pass


class AnthropicAdapter(LLMAdapter):
    """Adapter for Anthropic's Claude API."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model = config.get('model', 'claude-sonnet-4-20250514')
        self.max_tokens = config.get('max_tokens', 4096)
        self.temperature = config.get('temperature', 0.7)
        
        # Get API key from environment
        api_key_env = config.get('api_key_env', 'ANTHROPIC_API_KEY')
        api_key = os.environ.get(api_key_env)
        
        if not api_key:
            raise ValueError(f"API key not found in environment variable: {api_key_env}")
        
        self.client = anthropic.Anthropic(api_key=api_key)
        logger.info(f"Initialized Anthropic adapter with model: {self.model}")
    
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a response using Claude."""
        
        try:
            # Prepare parameters
            params = {
                "model": self.model,
                "max_tokens": kwargs.get('max_tokens', self.max_tokens),
                "temperature": kwargs.get('temperature', self.temperature),
                "messages": messages
            }
            
            if system:
                params["system"] = system
            
            if tools:
                params["tools"] = tools
            
            logger.debug(f"Calling Claude API with {len(messages)} messages")
            logger.debug(f"Tools available: {len(tools) if tools else 0}")
            
            # Call the API (synchronous client)
            response = self.client.messages.create(**params)
            
            # Parse response
            result = {
                "id": response.id,
                "model": response.model,
                "stop_reason": response.stop_reason,
                "content": [],
                "tool_calls": [],
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens
                }
            }
            
            # Extract content and tool calls
            for block in response.content:
                if block.type == "text":
                    result["content"].append({
                        "type": "text",
                        "text": block.text
                    })
                elif block.type == "tool_use":
                    result["tool_calls"].append({
                        "id": block.id,
                        "name": block.name,
                        "input": block.input
                    })
            
            logger.info(f"Claude response: {len(result['content'])} content blocks, "
                       f"{len(result['tool_calls'])} tool calls")
            logger.debug(f"Stop reason: {result['stop_reason']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error calling Claude API: {e}", exc_info=True)
            raise
    
    def format_tool_result(self, tool_call_id: str, content: str) -> Dict[str, Any]:
        """Format a tool result for inclusion in messages."""
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": content
                }
            ]
        }


def create_adapter(config: Dict[str, Any]) -> LLMAdapter:
    """Factory function to create an LLM adapter based on config."""
    provider = config.get('provider', 'anthropic').lower()
    
    if provider == 'anthropic':
        return AnthropicAdapter(config)
    elif provider == 'ollama':
        from ollama_adapter import OllamaAdapter
        return OllamaAdapter(config)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


async def main():
    """Test the LLM adapter."""
    import yaml
    from pathlib import Path
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load config
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    # Create adapter
    llm_config = config['llm']
    adapter = create_adapter(llm_config)
    
    # Test simple generation
    print("\n=== Testing Simple Generation ===")
    messages = [
        {"role": "user", "content": "What is 2+2? Answer briefly."}
    ]
    
    result = await adapter.generate(messages)
    
    print(f"\nResponse ID: {result['id']}")
    print(f"Stop Reason: {result['stop_reason']}")
    print(f"Usage: {result['usage']}")
    print("\nContent:")
    for content in result['content']:
        if content['type'] == 'text':
            print(content['text'])
    
    # Test with tools
    print("\n\n=== Testing with Tools ===")
    tools = [
        {
            "name": "get_weather",
            "description": "Get weather for a location",
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name"
                    }
                },
                "required": ["location"]
            }
        }
    ]
    
    messages = [
        {"role": "user", "content": "What's the weather in Paris?"}
    ]
    
    result = await adapter.generate(messages, tools=tools)
    
    print(f"\nTool Calls: {len(result['tool_calls'])}")
    for tool_call in result['tool_calls']:
        print(f"  - {tool_call['name']}: {tool_call['input']}")
    
    print("\nDone")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

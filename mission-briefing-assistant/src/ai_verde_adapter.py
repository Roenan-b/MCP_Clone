"""AI Verde LLM Adapter"""
import json
import logging
import os
from typing import Any, Dict, List, Optional
from llm_adapter import LLMAdapter

logger = logging.getLogger(__name__)


class AIVerdeAdapter(LLMAdapter):
    """Adapter for AI Verde (CyVerse) using OpenAI-compatible API."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model = config.get('model', 'Llama-3.3-70B-Instruct-quantized')
        self.max_tokens = config.get('max_tokens', 4096)
        self.temperature = config.get('temperature', 0.7)
        self.base_url = "https://llm-api.cyverse.ai/v1"
        
        # Get API key
        api_key = config.get('api_key')
        if not api_key:
            api_key_env = config.get('api_key_env', 'AI_VERDE_API_KEY')
            api_key = os.environ.get(api_key_env)
        
        if not api_key:
            raise ValueError(f"API key not found in config or environment")
        
        # AI Verde uses OpenAI-compatible API
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("OpenAI library not installed. Run: pip install openai")
        
        self.client = OpenAI(
            api_key=api_key,
            base_url=self.base_url
        )
        
        logger.info(f"Connected to AI Verde at {self.base_url}")
        logger.info(f"Using model: {self.model}")
    
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a response using AI Verde."""
        
        try:
            # Convert messages to OpenAI format
            openai_messages = []
            
            # Add system message
            if system:
                openai_messages.append({"role": "system", "content": system})
            
            # Process conversation messages
            for msg in messages:
                role = msg.get("role")
                content = msg.get("content")
                
                # Handle assistant messages with tool calls
                if role == "assistant" and isinstance(content, list):
                    text_parts = []
                    tool_calls = []
                    
                    for item in content:
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                        elif item.get("type") == "tool_use":
                            tool_calls.append({
                                "id": item.get("id"),
                                "type": "function",
                                "function": {
                                    "name": item.get("name"),
                                    "arguments": json.dumps(item.get("input", {}))
                                }
                            })
                    
                    openai_msg = {
                        "role": "assistant",
                        "content": " ".join(text_parts) if text_parts else None
                    }
                    
                    if tool_calls:
                        openai_msg["tool_calls"] = tool_calls
                    
                    openai_messages.append(openai_msg)
                
                # Handle user messages with tool results
                elif role == "user" and isinstance(content, list):
                    for item in content:
                        if item.get("type") == "tool_result":
                            openai_messages.append({
                                "role": "tool",
                                "tool_call_id": item.get("tool_use_id"),
                                "content": str(item.get("content", ""))
                            })
                        elif item.get("type") == "text":
                            openai_messages.append({
                                "role": "user",
                                "content": item.get("text", "")
                            })
                
                # Handle simple messages
                else:
                    openai_messages.append({
                        "role": role,
                        "content": str(content) if content else ""
                    })
            
            # Prepare API call parameters
            params = {
                "model": self.model,
                "messages": openai_messages,
                "max_tokens": kwargs.get('max_tokens', self.max_tokens),
                "temperature": kwargs.get('temperature', self.temperature),
            }
            
            # Add tools if provided
            if tools:
                params["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool["description"],
                            "parameters": tool["input_schema"]
                        }
                    }
                    for tool in tools
                ]
                params["tool_choice"] = "auto"
            
            logger.debug(f"Calling AI Verde API with {len(openai_messages)} messages")
            
            # Call AI Verde API
            response = self.client.chat.completions.create(**params)
            
            # Parse response
            result = {
                "id": response.id,
                "model": response.model,
                "stop_reason": response.choices[0].finish_reason,
                "content": [],
                "tool_calls": [],
                "usage": {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens
                }
            }
            
            message = response.choices[0].message
            
            # Extract text content
            if message.content:
                result["content"].append({
                    "type": "text",
                    "text": message.content
                })
            
            # Extract tool calls
            if message.tool_calls:
                for tc in message.tool_calls:
                    try:
                        arguments = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse tool arguments: {tc.function.arguments}")
                        arguments = {}
                    
                    result["tool_calls"].append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": arguments
                    })
            
            logger.info(f"AI Verde response: {len(result['content'])} content blocks, "
                       f"{len(result['tool_calls'])} tool calls")
            
            return result
            
        except Exception as e:
            logger.error(f"Error calling AI Verde API: {e}", exc_info=True)
            raise
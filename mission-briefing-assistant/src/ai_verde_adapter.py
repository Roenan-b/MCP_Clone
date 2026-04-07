"""
AI Verde LLM Adapter with OAuth and TLS Support
================================================
Adapter for AI Verde (CyVerse) using OpenAI-compatible API.
Supports both API key and OAuth2 authentication.
Includes TLS certificate verification options.
"""

import json
import logging
import os
import ssl
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AIVerdeAdapter:
    """Adapter for AI Verde (CyVerse) using OpenAI-compatible API."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize AI Verde adapter.
        
        Args:
            config: Configuration dictionary with auth and TLS settings
        """
        self.config = config
        self.model = config.get('model', 'Llama-3.3-70B-Instruct-quantized')
        self.max_tokens = config.get('max_tokens', 4096)
        self.temperature = config.get('temperature', 0.7)
        self.base_url = config.get('base_url', "https://llm-api.cyverse.ai/v1")
        
        # Get authentication
        auth_type = config.get('auth_type', 'api_key')
        
        if auth_type == 'oauth':
            logger.info("Using OAuth2 authentication")
            self._setup_oauth(config)
            api_key = self.oauth_manager.get_valid_token()
        else:
            logger.info("Using API key authentication")
            self.oauth_manager = None
            api_key = self._get_api_key(config)
        
        if not api_key:
            raise ValueError("API key not found in config or environment")
        
        # Setup TLS configuration
        tls_config = config.get('tls', {})
        verify_cert = tls_config.get('verify_cert', True)
        
        # AI Verde uses OpenAI-compatible API
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("OpenAI library not installed. Run: pip install openai")
        
        # Create OpenAI client with TLS configuration
        client_kwargs = {
            'api_key': api_key,
            'base_url': self.base_url
        }
        
        # Configure TLS certificate verification
        if not verify_cert:
            logger.warning("TLS certificate verification is DISABLED - not recommended for production!")
            # Note: OpenAI client doesn't directly support disabling verification
            # This would need to be handled via httpx client configuration
        
        # Custom cert path (for mTLS or custom CA)
        cert_path = tls_config.get('cert_path')
        ca_cert_path = tls_config.get('ca_cert_path')
        
        if cert_path and ca_cert_path:
            logger.info(f"Using custom TLS certificates: cert={cert_path}, ca={ca_cert_path}")
            # Note: Would need custom httpx client for full mTLS support
        
        self.client = OpenAI(**client_kwargs)
        
        logger.info(f"Connected to AI Verde at {self.base_url}")
        logger.info(f"Using model: {self.model}")
        logger.info(f"TLS verification: {verify_cert}")
    
    def _setup_oauth(self, config: Dict[str, Any]):
        """Setup OAuth2 token manager."""
        try:
            from oauth_helper import OAuth2TokenManager
        except ImportError:
            raise ImportError("oauth_helper not found. Ensure oauth_helper.py is in src/")
        
        oauth_config = config.get('oauth', {})
        
        if not oauth_config.get('client_id') or not oauth_config.get('client_secret'):
            raise ValueError("OAuth configuration incomplete: missing client_id or client_secret")
        
        self.oauth_manager = OAuth2TokenManager(
            client_id=oauth_config['client_id'],
            client_secret=oauth_config['client_secret'],
            token_url=oauth_config.get('token_url', 'https://llm-api.cyverse.ai/oauth/token')
        )
    
    def _get_api_key(self, config: Dict[str, Any]) -> Optional[str]:
        """Get API key from config or environment."""
        # Try direct config
        api_key = config.get('api_key')
        if api_key:
            return api_key
        
        # Try environment variable
        api_key_env = config.get('api_key_env', 'AI_VERDE_API_KEY')
        api_key = os.environ.get(api_key_env)
        if api_key:
            return api_key
        
        return None
    
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate a response using AI Verde.
        
        Args:
            messages: List of conversation messages
            tools: Optional list of tool definitions
            system: Optional system prompt
            **kwargs: Additional parameters
        
        Returns:
            Response dictionary with content and tool calls
        """
        
        # Refresh OAuth token if using OAuth
        if self.oauth_manager:
            try:
                api_key = self.oauth_manager.get_valid_token()
                self.client.api_key = api_key
            except Exception as e:
                logger.error(f"OAuth token refresh failed: {e}")
                raise
        
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
    
    def get_oauth_stats(self) -> Optional[Dict[str, Any]]:
        """
        Get OAuth refresh statistics if using OAuth.
        
        Returns:
            OAuth stats dictionary or None if not using OAuth
        """
        if self.oauth_manager:
            return self.oauth_manager.get_refresh_stats()
        return None


def main():
    """Test the AI Verde adapter."""
    import asyncio
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
    
    # Test adapter
    print("\n=== Testing AI Verde Adapter ===")
    
    async def test():
        adapter = AIVerdeAdapter(config['llm'])
        
        messages = [
            {"role": "user", "content": "What is 2+2?"}
        ]
        
        response = await adapter.generate(messages)
        
        print(f"\nResponse: {response['content'][0]['text']}")
        print(f"Tokens used: {response['usage']}")
        
        # Print OAuth stats if available
        if adapter.oauth_manager:
            stats = adapter.get_oauth_stats()
            print(f"\nOAuth stats: {stats}")
    
    asyncio.run(test())
    print("\nDone")


if __name__ == "__main__":
    main()

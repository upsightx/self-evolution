#!/usr/bin/env python3
"""
LLM Provider — 统一 LLM 调用抽象层。

所有模块通过此层访问 LLM，禁止各自硬编码 API 调用。
支持多 provider fallback 链：SiliconFlow → OpenRouter → None（降级到 proposal-only）。

环境变量：
  SILICONFLOW_API_KEY  — SiliconFlow API key
  OPENROUTER_API_KEY   — OpenRouter API key
  LLM_PROVIDER         — 强制指定 provider: siliconflow / openrouter / auto (default: auto)
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Standardized LLM response."""
    content: str
    provider: str
    model: str
    success: bool
    error: str = ""


# Provider configs
_PROVIDERS = {
    "siliconflow": {
        "url": "https://api.siliconflow.cn/v1/chat/completions",
        "env_key": "SILICONFLOW_API_KEY",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "headers_extra": {},
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "env_key": "OPENROUTER_API_KEY",
        "model": "qwen/qwen3.6-plus:free",
        "headers_extra": {
            "HTTP-Referer": "https://openclaw.ai",
            "X-Title": "OpenClaw Self-Evolution",
        },
    },
}


def _get_provider_order() -> list[str]:
    """Get provider fallback order based on config and available keys."""
    forced = os.environ.get("LLM_PROVIDER", "auto").lower()
    if forced != "auto" and forced in _PROVIDERS:
        return [forced]
    
    # Auto: try all providers with available keys
    available = []
    for name, cfg in _PROVIDERS.items():
        if os.environ.get(cfg["env_key"]):
            available.append(name)
    return available


def chat(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    max_tokens: int = 2000,
    timeout: int = 60,
) -> LLMResponse:
    """Send a chat completion request with automatic provider fallback.

    Args:
        prompt: User message
        system: Optional system message
        temperature: Sampling temperature
        max_tokens: Max response tokens
        timeout: Request timeout in seconds

    Returns:
        LLMResponse with content, provider info, and success status
    """
    providers = _get_provider_order()
    
    if not providers:
        return LLMResponse(
            content="",
            provider="none",
            model="none",
            success=False,
            error="No LLM API key available. Set SILICONFLOW_API_KEY or OPENROUTER_API_KEY.",
        )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_error = ""
    for provider_name in providers:
        cfg = _PROVIDERS[provider_name]
        api_key = os.environ.get(cfg["env_key"], "")
        if not api_key:
            continue

        try:
            data = json.dumps({
                "model": cfg["model"],
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }).encode("utf-8")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            headers.update(cfg["headers_extra"])

            req = urllib.request.Request(cfg["url"], data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                content = result["choices"][0]["message"]["content"].strip()
                return LLMResponse(
                    content=content,
                    provider=provider_name,
                    model=cfg["model"],
                    success=True,
                )

        except Exception as e:
            last_error = f"{provider_name}: {e}"
            print(f"[llm_provider] {provider_name} failed: {e}")
            continue

    return LLMResponse(
        content="",
        provider="none",
        model="none",
        success=False,
        error=f"All providers failed. Last error: {last_error}",
    )


def generate_code_patch(
    suggestion: str,
    current_code: str,
    task_type: str = "",
    max_code_chars: int = 3000,
) -> str | None:
    """Generate a code patch based on a suggestion. Convenience wrapper.

    Args:
        suggestion: What to improve
        current_code: Current file content (truncated to max_code_chars)
        task_type: Context about the task type
        max_code_chars: Max chars of current code to include

    Returns:
        Modified code string, or None if generation failed
    """
    prompt = f"""You are an AI Agent framework engineer. Improve the following code based on the suggestion.

Task Type: {task_type}
Improvement Suggestion: {suggestion}

Current Code:
```
{current_code[:max_code_chars]}
```

Instructions:
1. Apply the suggestion to improve the code.
2. Return ONLY the complete modified code.
3. Do not include explanations, just the code.
4. Keep the same structure and style.

Return the full modified code below:
"""

    response = chat(prompt, temperature=0.3, max_tokens=4000, timeout=90)
    if not response.success:
        print(f"[llm_provider] Code patch generation failed: {response.error}")
        return None

    # Strip markdown code fences
    content = response.content
    content = content.replace("```python", "").replace("```", "").strip()
    return content


def is_available() -> bool:
    """Check if any LLM provider is available."""
    return len(_get_provider_order()) > 0


def get_status() -> dict:
    """Get provider availability status."""
    status = {}
    for name, cfg in _PROVIDERS.items():
        key = os.environ.get(cfg["env_key"], "")
        status[name] = {
            "available": bool(key),
            "model": cfg["model"],
            "key_prefix": key[:8] + "..." if key else "not set",
        }
    return status

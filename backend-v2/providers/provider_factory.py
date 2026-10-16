"""
Provider Factory

Creates and manages AI provider instances based on configuration.
Handles fallback logic and provider selection.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .models import (
    ProviderConfig,
    MultimodalConfig,
    MultimodalAIProvider,
    ProviderError,
)
from .gemini_provider import GeminiProvider
from .openai_provider import OpenAIProvider
from .offline_provider import OfflineProvider


# Provider classes available for factory
# Registration is deferred to factory initialization to avoid import-time instantiation issues


#: Current model per provider and capability, unless AI_<KIND>_MODEL is set.
_DEFAULT_MODELS = {
    "gemini": {
        "TEXT": "gemini-flash-lite-latest",
        "VISION": "gemini-flash-latest",
        "MULTIMODAL": "gemini-flash-latest",
    },
    "openai": {"TEXT": "gpt-4o-mini", "VISION": "gpt-4o", "MULTIMODAL": "gpt-4o"},
}
_KEY_VARS = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}


class ProviderFactory:
    """
    Factory for creating and managing AI provider instances.
    
    Handles:
    - Configuration-driven provider selection
    - Fallback provider chains
    - Health checks
    - Cost-aware routing
    """
    
    def __init__(self, config: Optional[MultimodalConfig] = None):
        self.config = config or self._load_from_env()
        self._providers: Dict[str, MultimodalAIProvider] = {}
    
    # Placeholder / obviously-invalid credential markers. Real provider keys
    # never contain these; seeing them means the deployment has not been
    # configured, so we must NOT attempt live API calls (they 401).
    _PLACEHOLDER_MARKERS = ("test-key", "test_key", "your-", "your_", "changeme",
                            "placeholder", "xxx", "<api", "dummy", "example")

    @classmethod
    def _has_usable_credential(cls, key: Optional[str]) -> bool:
        if not key:
            return False
        lowered = key.strip().lower()
        if not lowered:
            return False
        return not any(marker in lowered for marker in cls._PLACEHOLDER_MARKERS)

    @classmethod
    def _offline_mode_requested(cls) -> bool:
        """True when the operator explicitly asked for the offline provider."""
        mode = os.getenv("AI_PROVIDER_MODE", "").strip().lower()
        return mode in ("offline", "mock", "local", "rules")

    @classmethod
    def _should_use_offline(cls) -> bool:
        """Use the deterministic offline provider when explicitly requested
        OR when no usable live credential is configured.

        This keeps the platform fully exercisable (E2E, demos, offline
        clinics) instead of failing every request with a provider 401.
        """
        if cls._offline_mode_requested():
            return True
        if os.getenv("AI_FORCE_LIVE", "").strip().lower() in ("1", "true", "yes"):
            return False
        gemini = os.getenv("GEMINI_API_KEY")
        openai = os.getenv("OPENAI_API_KEY")
        return not (
            cls._has_usable_credential(gemini) or cls._has_usable_credential(openai)
        )

    @classmethod
    def _default_live_provider(cls) -> str:
        """The provider whose credential is configured; Gemini when both are."""
        if cls._has_usable_credential(os.getenv("GEMINI_API_KEY")):
            return "gemini"
        if cls._has_usable_credential(os.getenv("OPENAI_API_KEY")):
            return "openai"
        return "gemini"

    def _load_from_env(self) -> MultimodalConfig:
        """Load configuration from environment variables.

        When offline mode is active every slot is pinned to the `offline`
        provider so no live network call can be attempted.
        """
        offline = self._should_use_offline()

        def slot(kind: str, temperature_var: str, default_temperature: str, **extra) -> ProviderConfig:
            """One capability slot, with the key and model of *its* provider.

            Text used to default to OpenAI even when only a Gemini key was
            configured (every text request then failed with a 401), and the
            vision slots were handed whichever key existed, possibly the other
            provider's.
            """
            provider = os.getenv(f"AI_{kind}_PROVIDER", "").strip().lower() or self._default_live_provider()
            if offline or provider == "offline":
                # One capability can be pinned offline while others are live.
                return ProviderConfig(provider="offline", model="dedan-rules-v1", **extra)
            model = os.getenv(f"AI_{kind}_MODEL") or _DEFAULT_MODELS.get(provider, {}).get(kind)
            if not model:
                raise ValueError(
                    f"AI_{kind}_PROVIDER={provider!r} has no default model; set AI_{kind}_MODEL."
                )
            return ProviderConfig(
                provider=provider,
                model=model,
                api_key=os.getenv(_KEY_VARS.get(provider, "")),
                temperature=float(os.getenv(temperature_var, default_temperature)),
                **extra,
            )

        return MultimodalConfig(
            text_provider=slot(
                "TEXT", "AI_TEMPERATURE", "0.3",
                max_tokens=int(os.getenv("AI_MAX_TOKENS", "0")) or None,
            ),
            vision_provider=slot("VISION", "AI_VISION_TEMPERATURE", "0.2"),
            multimodal_provider=slot("MULTIMODAL", "AI_MULTIMODAL_TEMPERATURE", "0.3"),
            enable_fallback=os.getenv("AI_ENABLE_FALLBACK", "true").lower() == "true",
            fallback_providers=os.getenv("AI_FALLBACK_PROVIDERS", "").split(",") if os.getenv("AI_FALLBACK_PROVIDERS") else [],
            max_cost_per_request_usd=float(os.getenv("AI_MAX_COST_PER_REQUEST", "1.0")),
            daily_budget_usd=float(os.getenv("AI_DAILY_BUDGET", "0")) or None,
            safety_threshold=float(os.getenv("AI_SAFETY_THRESHOLD", "0.7")),
            require_professional_review_threshold=float(os.getenv("AI_REVIEW_THRESHOLD", "0.8")),
        )
    
    def get_text_provider(self) -> MultimodalAIProvider:
        """Get the configured text analysis provider."""
        return self._get_or_create_provider(
            self.config.text_provider.provider,
            self.config.text_provider.dict()
        )
    
    def get_vision_provider(self) -> MultimodalAIProvider:
        """Get the configured vision analysis provider."""
        return self._get_or_create_provider(
            self.config.vision_provider.provider,
            self.config.vision_provider.dict()
        )
    
    def get_multimodal_provider(self) -> MultimodalAIProvider:
        """Get the configured multimodal analysis provider."""
        return self._get_or_create_provider(
            self.config.multimodal_provider.provider,
            self.config.multimodal_provider.dict()
        )
    
    def get_provider_for_modalities(
        self,
        has_text: bool = False,
        has_image: bool = False,
        has_audio: bool = False,
    ) -> MultimodalAIProvider:
        """Select the best provider based on input modalities."""
        if has_image or has_audio:
            return self.get_multimodal_provider()
        return self.get_text_provider()
    def _get_or_create_provider(
        self,
        provider_name: str,
        config: Dict[str, Any],
    ) -> MultimodalAIProvider:
        """Get cached provider or create new instance."""
        cache_key = f"{provider_name}:{config.get('model', '')}"
        
        if cache_key not in self._providers:
            provider_config = {**config, "provider": provider_name}
            self._providers[cache_key] = self._create_provider(provider_name, provider_config)
        
        return self._providers[cache_key]
    
    def _create_provider(self, provider_name: str, config: Dict[str, Any]) -> MultimodalAIProvider:
        """Create provider instance directly."""
        if provider_name == "gemini":
            return GeminiProvider(config)
        elif provider_name == "openai":
            return OpenAIProvider(config)
        elif provider_name == "offline":
            return OfflineProvider(config)
        else:
            raise ProviderError(f"Unknown provider: {provider_name}", provider_name, "", "UNKNOWN_PROVIDER")
    
    async def health_check_all(self) -> Dict[str, bool]:
        """Check health of all configured providers."""
        results = {}
        for provider_name in ["text", "vision", "multimodal"]:
            try:
                provider = getattr(self, f"get_{provider_name}_provider")()
                results[provider_name] = await provider.health_check()
            except Exception as e:
                results[provider_name] = False
        return results
    
    def get_available_providers(self) -> List[str]:
        """List all available provider names."""
        return ["gemini", "openai", "offline"]
    
    def get_all_capabilities(self) -> Dict[str, Any]:
        """Get capabilities of all available providers."""
        capabilities = {}
        for name in ["gemini", "openai", "offline"]:
            try:
                provider = self._create_provider(name, {})
                capabilities[name] = provider.capabilities
            except Exception:
                pass
        return capabilities
    
    async def with_fallback(
        self,
        primary_provider: MultimodalAIProvider,
        operation: str,
        *args,
        **kwargs,
    ) -> Any:
        """
        Execute operation with fallback to secondary providers.
        
        Args:
            primary_provider: Primary provider to try first
            operation: Method name to call (e.g., "analyze_text")
            *args, **kwargs: Arguments to pass to the method
            
        Returns:
            Result from primary or fallback provider
            
        Raises:
            ProviderError: If all providers fail
        """
        providers_to_try = [primary_provider]
        
        if self.config.enable_fallback:
            for fallback_name in self.config.fallback_providers:
                if fallback_name and fallback_name != primary_provider.provider_name:
                    try:
                        fallback = self._get_or_create_provider(fallback_name, {})
                        providers_to_try.append(fallback)
                    except Exception:
                        continue
        
        last_error = None
        for provider in providers_to_try:
            try:
                method = getattr(provider, operation)
                return await method(*args, **kwargs)
            except Exception as e:
                last_error = e
                if self._should_fallback(e):
                    continue
                else:
                    raise
        
        raise ProviderError(
            f"All providers failed. Last error: {last_error}",
            "factory", "multiple", "ALL_PROVIDERS_FAILED"
        )
    
    def _should_fallback(self, error: Exception) -> bool:
        """Determine if error should trigger fallback."""
        from .models import (
            ProviderUnavailableError,
            ProviderRateLimitError,
            ProviderTimeoutError,
        )
        return isinstance(error, (
            ProviderUnavailableError,
            ProviderRateLimitError,
            ProviderTimeoutError,
        ))
    
    def estimate_request_cost(
        self,
        provider: MultimodalAIProvider,
        prompt_tokens: int,
        completion_tokens: int,
        image_tokens: int = 0,
    ) -> float:
        """Estimate cost for a request."""
        from .models import TokenUsage
        tokens = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            image_tokens=image_tokens,
        )
        return provider.estimate_cost(tokens)
    
    def check_cost_limit(self, estimated_cost: float) -> bool:
        """Check if estimated cost is within limits."""
        if estimated_cost > self.config.max_cost_per_request_usd:
            return False
        return True


# Global factory instance
_factory: Optional[ProviderFactory] = None


def get_provider_factory(config: Optional[MultimodalConfig] = None) -> ProviderFactory:
    """Get or create the global provider factory."""
    global _factory
    if _factory is None:
        _factory = ProviderFactory(config)
    return _factory


def reset_provider_factory():
    """Reset the global factory (useful for testing)."""
    global _factory
    _factory = None

"""Which adapter answers for a provider code.

A code with no adapter — or the reference connector outside test and
development — gets an adapter that declares no capability. Nothing raises: the
connection simply has nothing it can do, and the screen says so (H11). Only real
adapters, implemented and homologated per channel, ever add capabilities here.
"""

from app.core.config import settings
from app.modules.channels.adapters import reference
from app.modules.channels.contracts import ChannelAdapter

TEST_ENVIRONMENTS = frozenset({"test", "development"})


class UnavailableChannelAdapter:
    """A provider the platform cannot talk to. It declares nothing, and is called for nothing."""

    parser_version = "unavailable"
    capabilities: frozenset = frozenset()

    def __init__(self, provider_code: str) -> None:
        self.provider_code = provider_code


def adapter_for(provider_code: str) -> ChannelAdapter:
    code = (provider_code or "").strip().upper()
    if code == reference.PROVIDER_CODE and settings.ENVIRONMENT.strip().lower() in TEST_ENVIRONMENTS:
        return reference.ReferenceChannelAdapter()
    return UnavailableChannelAdapter(code)

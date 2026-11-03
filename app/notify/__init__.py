from dataclasses import dataclass, field


@dataclass
class SendResult:
    status: str  # sent | simulated | failed
    provider: str
    recipient: str
    provider_message_id: str = ""
    error: str = ""
    extra: dict = field(default_factory=dict)

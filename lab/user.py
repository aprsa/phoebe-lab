from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class User:
    """
    User identification for PHOEBE Lab sessions.

    Stores student metadata to be attached to server sessions for tracking purposes.
    No authentication - just identification.
    """

    first_name: str
    last_name: str
    email: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        """Convert user to dictionary for passing to session API."""
        return {
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'timestamp': self.timestamp,
        }

    @property
    def full_name(self) -> str:
        """Return full name for display."""
        return f'{self.first_name} {self.last_name}'

    @classmethod
    def from_dict(cls, data: dict) -> 'User':
        """Create User from dictionary (e.g., from storage)."""
        return cls(
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            email=data.get('email', ''),
            timestamp=data.get('timestamp', datetime.now().isoformat()),
        )

from pydantic import BaseModel


class RateCard(BaseModel):
    currency: str = "IDR"
    per_day: dict[str, int]


def price(effort_days: dict[str, float], rc: RateCard) -> int:
    """Rupiah for a person-day breakdown; an unknown role is an error."""
    total = 0.0
    for role, days in effort_days.items():
        if role not in rc.per_day:
            raise KeyError(f"role '{role}' is not on the rate card")
        total += days * rc.per_day[role]
    return int(round(total))

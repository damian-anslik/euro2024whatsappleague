from pydantic import BaseModel


class League(BaseModel):
    id: int
    name: str
    season: str
    show_by_default: bool = False

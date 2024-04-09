from pydantic import BaseModel


class League(BaseModel):
    id: str
    name: str
    season: str
    show_by_default: bool = False

# state.py
from typing import List, Dict, Any, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field

# Structured extraction target for Gemini Flash 3 Lite
class CarDetails(BaseModel):
    make: Optional[str] = Field(None, description="The manufacturer, e.g., Toyota")
    model: Optional[str] = Field(None, description="The specific model, e.g., Hilux")
    year: Optional[int] = Field(None, description="The manufacturing year, e.g., 2019")
    mileage: Optional[int] = Field(None, description="Odometer reading in kilometers")

# LangGraph state layout
class AgentState(TypedDict):
    messages: List[Dict[str, Any]]        # Conversation history mapping
    extracted_details: Dict[str, Any]      # Extracted Pydantic parameters
    historical_data: Optional[Dict[str, Any]] # Metrics found in DB
    scraped_data: Optional[List[Dict[str, Any]]] # Live data from Cars45
    pricing_recommendation: Optional[Dict[str, Any]] # Results from math engine
    next_step: str                        # Router directional command
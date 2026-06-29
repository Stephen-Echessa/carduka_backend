# graph.py
import os
import json
import asyncio
import aiosqlite
from typing import Literal, Optional
from pydantic import BaseModel, Field

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, HumanMessage

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import MessagesState
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from tools import query_historical_sales, scrape_cars45_listings, extract_text

from dotenv import load_dotenv
load_dotenv()

# --- 1. State Definition ---
class CarDetails(BaseModel):
    make: Optional[str] = Field(None, description="The manufacturer, e.g., Toyota")
    model: Optional[str] = Field(None, description="The specific model, e.g., Hilux")
    year: Optional[int] = Field(None, description="The manufacturing year, e.g., 2019")
    mileage: Optional[int] = Field(None, description="Odometer reading in kilometers, e.g., 80000")

class AgentState(MessagesState):
    extracted_details: CarDetails
    historical_data: Optional[dict]
    scraped_data: Optional[list]
    pricing_recommendation: Optional[dict]


# --- 2. Build Agent Engine Pipeline ---
async def build_agent():
    # Initialize the Gemini model via LangChain's native wrapper
    model = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0.2)

    # --- Nodes ---
    
    async def extract_intent_node(state: AgentState):
        """Extracts car details structured schema from the chat history."""
        print("\n========== [STEP 1: INTENT EXTRACTION] ==========")
        print(f"📥 Input History Length: {len(state.get('messages', []))} messages")

        intent_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an automotive market parameter extractor. Analyze the conversation history and extract the following metrics: make, model, year, and mileage. If a parameter is not explicitly provided, leave it as null."),
            MessagesPlaceholder("messages"),
        ])
        
        # Bind the Pydantic schema for strict deterministic extraction output
        structured_model = model.with_structured_output(CarDetails)
        extraction_chain = intent_prompt | structured_model
        
        # We process the recent conversation messages
        response = await extraction_chain.ainvoke({"messages": state["messages"]})

        print(f"📤 Extracted Specs: {response}")
        return {"extracted_details": response}


    async def ask_clarifying_questions_node(state: AgentState):
        """Asks the user for missing required car fields."""
        details = state["extracted_details"]
        missing_fields = []
        if not details.make: missing_fields.append("manufacturer make")
        if not details.model: missing_fields.append("model name")
        if not details.year: missing_fields.append("manufacturing year")
        if not details.mileage: missing_fields.append("mileage in km")
        
        prompt = f"The user is looking for a valuation, but we are missing: {', '.join(missing_fields)}. Politely ask the user to provide these remaining data points."
        response = await model.ainvoke(prompt)
        
        # Clean the textual output using your helper
        clean_text = extract_text(response.content)
        
        return {"messages": [AIMessage(content=clean_text)]}


    async def execute_tools_node(state: AgentState):
        """Queries the local SQLite marketplace and scrapes Cars45 live endpoints."""
        print("\n========== [STEP 2: TOOL RETRIEVAL] ==========")
        print(f"📥 Querying with parameters: {state['extracted_details']}")

        details = state["extracted_details"]
        
        # 1. Gather historical data from local SQLite database (Synchronous wrapper call)
        db_metrics = query_historical_sales(
            make=details.make,
            model=details.model,
            year=int(details.year),
            mileage=int(details.mileage)
        )
        
        # 2. Scrape live data off Cars45 marketplace
        try:
            # Running synchronous scraper safely in executors if necessary, or basic function wrapper
            scraped_listings = scrape_cars45_listings(make=details.make, model=details.model, year=details.year)

            print("📋 [Raw DB Metrics Output Payload]:")
            print(json.dumps(db_metrics, indent=2, default=str))
            print(f"📤 Database Metrics Samples Found: {db_metrics.get('count', 0)}")

            print(f"📤 Scraped Listings Count: {len(scraped_listings) if scraped_listings else 0}")
            print("\n🌐 [Raw Scraped Listings Output Payload]:")
            print(json.dumps(scraped_listings, indent=2, default=str))

            return {
                "historical_data": db_metrics,
                "scraped_data": scraped_listings,
                "pricing_recommendation": None
            }
        except RuntimeError as err:
            # Capture webscraping failure and pass through pipeline as strict exception marker
            return {
                "historical_data": db_metrics,
                "scraped_data": None,
                "pricing_recommendation": {"error": str(err)}
            }


    async def pricing_engine_node(state: AgentState):
        """A purely deterministic math engine computing price limits based on metrics data."""
        print("\n========== [STEP 3: DETERMINISTIC MATH] ==========")
        # If upstream scraping threw an exception block, skip calculation node execution
        if state.get("pricing_recommendation") and "error" in state["pricing_recommendation"]:
            return {}
            
        db_data = state.get("historical_data", {})
        
        # Default price fallbacks if db query found absolutely 0 comparative data windows
        if "error" in db_data:
            median_anchor = 4200000 
        else:
            median_anchor = db_data["avg_price"]
            
        res = {
            "competitive_min": int(median_anchor * 0.92),
            "competitive_max": int(median_anchor * 1.08),
            "recommended_listing": int(median_anchor)
        }

        print(f"📤 Math Calculations Output: {res}")
        return {"pricing_recommendation": res}


    async def synthesize_response_node(state: AgentState):
        """Blends calculations with scraped market context and adds the legal disclaimer."""
        pricing = state.get("pricing_recommendation", {})
        
        # Check if the process stopped due to a scraping failure
        if pricing and "error" in pricing:
            err_output = (
                f"⚠️ **System Interruption**: Processing halted due to an external network dependency issue:\n"
                f"`{pricing['error']}`\n\n"
                "Please review the connection strings or try again later."
            )
            return {"messages": [AIMessage(content=err_output)]}
            
        details = state["extracted_details"]
        scraped = state.get("scraped_data", [])
        
        system_prompt = f"""
        You are an expert dealer advisory system for CarDuka Kenya. Formulate a conversational valuation overview using this information:
        
        - Vehicle Specs: {details.year} {details.make} {details.model} ({details.mileage:,} km)
        - Targeted Suggestion Price: KSh {pricing.get('recommended_listing'):,}
        - Market Range: KSh {pricing.get('competitive_min'):,} to KSh {pricing.get('competitive_max'):,}
        - Live Scrape Data points: {scraped}
        
        CRITICAL REQUISITE: You must display this EXACT textual disclaimer verbatim at the bottom of your output:
        "This recommendation is based on available market data and is not a guarantee of sale price. Actual value may vary based on vehicle condition, service history, and market demand. This is not a formal valuation."
        """
        
        response = await model.ainvoke(system_prompt)
        
        # Clean the output payload text cleanly
        clean_text = extract_text(response.content)
        
        return {"messages": [AIMessage(content=clean_text)]}


    # --- 3. Conditional Routing Logic ---
    def check_details_router(state: AgentState) -> Literal["execute_tools_node", "ask_clarifying_questions_node"]:
        details = state.get("extracted_details")
        if details and details.make and details.model and details.year and details.mileage:
            return "execute_tools_node"
        return "ask_clarifying_questions_node"


    # --- 4. Wire Up The State Graph ---
    graph_builder = StateGraph(AgentState)

    graph_builder.add_node("extract_intent_node", extract_intent_node)
    graph_builder.add_node("ask_clarifying_questions_node", ask_clarifying_questions_node)
    graph_builder.add_node("execute_tools_node", execute_tools_node)
    graph_builder.add_node("pricing_engine_node", pricing_engine_node)
    graph_builder.add_node("synthesize_response_node", synthesize_response_node)

    graph_builder.add_edge(START, "extract_intent_node")
    graph_builder.add_conditional_edges(
        "extract_intent_node",
        check_details_router,
        {
            "execute_tools_node": "execute_tools_node",
            "ask_clarifying_questions_node": "ask_clarifying_questions_node"
        }
    )
    graph_builder.add_edge("ask_clarifying_questions_node", END)
    graph_builder.add_edge("execute_tools_node", "pricing_engine_node")
    graph_builder.add_edge("pricing_engine_node", "synthesize_response_node")
    graph_builder.add_edge("synthesize_response_node", END)

    # Initialize async sqlite connection framework for state snapshots
    conn = aiosqlite.connect("checkpoints.db", check_same_thread=False)
    memory = AsyncSqliteSaver(conn)
    
    graph = graph_builder.compile(checkpointer=memory)

    # Export graph workflow representation blueprint structure
    try:
        png_bytes = graph.get_graph().draw_mermaid_png()
        with open("pricing_agent_graph.png", "wb") as f:
            f.write(png_bytes)
    except Exception:
        pass # Handle elegantly if pygraphviz/mermaid dependencies aren't loaded globally

    return graph
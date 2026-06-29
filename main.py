# main.py
import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage, AIMessage

from database import init_and_seed_db
from graph import build_agent

# --- 1. Lifespan Event Manager ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🤖 Booting market valuation backend...")
    
    # Initialize and seed our mock local database with Kenyan pricing records
    init_and_seed_db()
    
    # Asynchronously compile our LangGraph engine
    print("Building agent...")
    agent = await build_agent()
    app.state.agent = agent
    print("🚀 Pricing agent ready for production.")
    
    yield
    
    print("🛑 Shutting down backend.")


app = FastAPI(title="CarDuka Agentic Valuation Backend", lifespan=lifespan)

# --- 2. CORS Middleware Configuration ---
origins = [
    "http://localhost:3000",   # Next.js local development port
    "http://127.0.0.1:3000",
    "https://carduka-frontend.vercel.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"status": "healthy"}


# --- 3. Stateful WebSocket Endpoint ---
@app.websocket("/ws/chat/{thread_id}")
async def websocket_endpoint(websocket: WebSocket, thread_id: str):
    """
    Handles stateful real-time chat sessions using a JSON-based protocol.
    The thread_id maps directly to the LangGraph checkpointer thread context.
    """
    await websocket.accept()
    print(f"🔌 WebSocket established for session thread_id: {thread_id}")
    
    agent = app.state.agent
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        # Restore and transmit conversation history if it exists in checkpointer
        state = await agent.aget_state(config)
        if state and state.values:
            history = []
            for msg in state.values.get("messages", []):
                if isinstance(msg, HumanMessage):
                    history.append({"role": "user", "content": msg.content})
                elif isinstance(msg, AIMessage):
                    history.append({"role": "assistant", "content": msg.content})
            
            if history:
                print(f"🔄 Restoring {len(history)} messages for thread_id: {thread_id}")
                await websocket.send_json({"type": "history", "messages": history})
        
        # Main persistent interaction frame loop
        while True:
            # Receive structured structured request from Next.js
            data = await websocket.receive_json()
            user_message = data.get("message", "").strip()
            
            if not user_message:
                continue
                
            # Send status update indicating the graph computation pipeline is running
            await websocket.send_json({"type": "status", "message": "Analyzing market metrics..."})
            
            try:
                # Fire graph sequence updates down the pipeline state engine
                result = await agent.ainvoke(
                    {"messages": [HumanMessage(content=user_message)]},
                    config=config
                )
                
                messages = result.get("messages", [])
                reply_text = ""
                if messages:
                    last_msg = messages[-1]
                    reply_text = getattr(last_msg, "content", str(last_msg))
                
                # Push successful model outcome message frame
                await websocket.send_json({
                    "type": "message",
                    "message": reply_text
                })
                
            except Exception as graph_err:
                print(f"⚠️ Agent pipeline processing runtime error: {graph_err}")
                await websocket.send_json({
                    "type": "error", 
                    "message": "Something went wrong processing your request. Please try again."
                })
                
    except WebSocketDisconnect:
        print(f"❌ WebSocket disconnected for session thread_id: {thread_id}")
    except Exception as e:
        print(f"⚠️ Exception occurred within socket pipeline lifecycle: {str(e)}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main.py", host="0.0.0.0", port=port, log_level="info")
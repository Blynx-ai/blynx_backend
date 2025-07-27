from datetime import datetime
from typing import Dict, List, Optional
from fastapi import HTTPException, Depends, status, APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from auth import auth_service, UserResponse
from business import business_service
from agent_flow_manager import agent_flow_manager, FlowStatus
import json
import asyncio
import logging

logger = logging.getLogger(__name__)

# Pydantic models
class AgentFlowTriggerRequest(BaseModel):
    source_url: Optional[str] = None  # Optional - will use business URLs if not provided

class AgentFlowResponse(BaseModel):
    flow_id: str
    status: str
    source_urls: List[str]
    created_at: datetime

class AgentFlowResult(BaseModel):
    flow_id: str
    status: str
    blynx_score: Optional[Dict] = None
    feedback: Optional[Dict] = None
    analysis_details: Optional[Dict] = None
    created_at: datetime

class AgentFlowStatus(BaseModel):
    flow_id: str
    status: str
    progress: str
    current_agent: str
    timestamp: datetime

# Create router
router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, flow_id: str):
        await websocket.accept()
        self.active_connections[flow_id] = websocket
        logger.info(f"WebSocket connected for flow {flow_id}")
    
    def disconnect(self, flow_id: str):
        if flow_id in self.active_connections:
            del self.active_connections[flow_id]
            logger.info(f"WebSocket disconnected for flow {flow_id}")
    
    async def send_logs(self, flow_id: str, logs: List[Dict]):
        if flow_id in self.active_connections:
            try:
                await self.active_connections[flow_id].send_text(json.dumps({
                    "type": "logs",
                    "data": logs
                }))
            except Exception as e:
                logger.error(f"Error sending logs to websocket: {e}")
                self.disconnect(flow_id)
    
    async def send_status(self, flow_id: str, status: str, is_final: bool = False):
        if flow_id in self.active_connections:
            try:
                await self.active_connections[flow_id].send_text(json.dumps({
                    "type": "status",
                    "data": {
                        "status": status,
                        "final": is_final,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                }))
            except Exception as e:
                logger.error(f"Error sending status to websocket: {e}")
                self.disconnect(flow_id)

manager = ConnectionManager()

class AgentService:
    @staticmethod
    async def trigger_agent_flow(request: AgentFlowTriggerRequest, user_id: int) -> AgentFlowResponse:
        """Trigger agent flow using business data"""
        try:
            # Get user's business
            business = await business_service.get_business(user_id)
            
            # Collect URLs from business data
            source_urls = []
            if request.source_url:
                source_urls.append(request.source_url)
            else:
                # Use business URLs
                if business.landing_page_url:
                    source_urls.append(business.landing_page_url)
                if business.instagram_url:
                    source_urls.append(business.instagram_url)
                if business.linkedin_url:
                    source_urls.append(business.linkedin_url)
                if business.x_url:
                    source_urls.append(business.x_url)
            
            if not source_urls:
                raise ValueError("No URLs available. Please add URLs to your business profile or provide a source URL.")
            
            # Start the agent flow with all URLs
            flow_id = await agent_flow_manager.start_agent_flow(
                user_id=user_id,
                source_urls=source_urls,
                business_id=business.id,
                business_data=business
            )
            
            return AgentFlowResponse(
                flow_id=flow_id,
                status=FlowStatus.PENDING.value,
                source_urls=source_urls,
                created_at=datetime.utcnow()
            )
            
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        except Exception as e:
            logger.error(f"Error triggering agent flow: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to trigger agent flow"
            )
    
    @staticmethod
    async def stop_agent_flow(flow_id: str, user_id: int) -> Dict[str, str]:
        """Stop an active agent flow"""
        try:
            success = await agent_flow_manager.stop_agent_flow(user_id, flow_id)
            
            if success:
                # Notify via WebSocket
                await manager.send_status(flow_id, FlowStatus.STOPPED.value, True)
                return {"message": "Agent flow stopped successfully"}
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Flow not found or not active"
                )
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error stopping agent flow: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to stop agent flow"
            )
    
    @staticmethod
    async def get_flow_status(flow_id: str, user_id: int) -> AgentFlowStatus:
        """Get the status of an agent flow"""
        try:
            flow_status = agent_flow_manager.get_flow_status(flow_id)
            
            if flow_status is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Flow not found"
                )
            
            # Get latest log to determine current agent/progress
            logs = agent_flow_manager.get_flow_logs(flow_id)
            current_agent = "SYSTEM"
            progress = "Initializing..."
            
            if logs:
                latest_log = logs[-1]
                current_agent = latest_log.get("agent", "SYSTEM")
                progress = latest_log.get("message", "Processing...")
            
            return AgentFlowStatus(
                flow_id=flow_id,
                status=flow_status.value,
                progress=progress,
                current_agent=current_agent,
                timestamp=datetime.utcnow()
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting flow status: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get flow status"
            )
    
    @staticmethod
    async def get_flow_result(flow_id: str, user_id: int) -> AgentFlowResult:
        """Get the result of a completed agent flow"""
        try:
            result = agent_flow_manager.get_flow_result(flow_id)
            flow_status = agent_flow_manager.get_flow_status(flow_id)
            
            if result is None:
                if flow_status == FlowStatus.COMPLETED:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Flow result not found"
                    )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Flow is not completed yet. Current status: {flow_status.value if flow_status else 'unknown'}"
                    )
            
            return AgentFlowResult(
                flow_id=flow_id,
                status=flow_status.value if flow_status else "unknown",
                blynx_score=result.get("blynx_score"),
                feedback=result.get("feedback"),
                analysis_details=result.get("analysis_details"),
                created_at=datetime.fromisoformat(result.get("timestamp", datetime.utcnow().isoformat()))
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting flow result: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get flow result"
            )

# Create agent service instance
agent_service = AgentService()

# Routes
@router.post("/trigger", response_model=AgentFlowResponse)
async def trigger_agent_flow(
    request: AgentFlowTriggerRequest,
    current_user: UserResponse = Depends(auth_service.get_current_user)
):
    """Trigger agent flow using business data or provided URL"""
    return await agent_service.trigger_agent_flow(request, current_user.id)

@router.post("/stop/{flow_id}")
async def stop_agent_flow(
    flow_id: str,
    current_user: UserResponse = Depends(auth_service.get_current_user)
):
    """Stop an active agent flow"""
    return await agent_service.stop_agent_flow(flow_id, current_user.id)

@router.get("/status/{flow_id}", response_model=AgentFlowStatus)
async def get_flow_status(
    flow_id: str,
    current_user: UserResponse = Depends(auth_service.get_current_user)
):
    """Get the status of an agent flow"""
    return await agent_service.get_flow_status(flow_id, current_user.id)

@router.get("/result/{flow_id}", response_model=AgentFlowResult)
async def get_flow_result(
    flow_id: str,
    current_user: UserResponse = Depends(auth_service.get_current_user)
):
    """Get the result of a completed agent flow"""
    return await agent_service.get_flow_result(flow_id, current_user.id)

@router.websocket("/logs/{flow_id}")
async def websocket_logs(websocket: WebSocket, flow_id: str):
    """WebSocket endpoint for real-time flow logs
    
    Usage: ws://localhost:8000/api/v1/agents/logs/{flow_id}
    
    Messages received:
    - {"type": "logs", "data": [log_entries]}
    - {"type": "status", "data": {"status": "completed", "final": true}}
    """
    await manager.connect(websocket, flow_id)
    try:
        # Send initial logs
        logs = agent_flow_manager.get_flow_logs(flow_id)
        await manager.send_logs(flow_id, logs)
        
        # Send initial status
        flow_status = agent_flow_manager.get_flow_status(flow_id)
        if flow_status:
            await manager.send_status(flow_id, flow_status.value)
        
        # Keep connection alive and send updates
        last_log_count = len(logs)
        while True:
            await asyncio.sleep(1)  # Check every second
            
            current_logs = agent_flow_manager.get_flow_logs(flow_id)
            if len(current_logs) > last_log_count:
                # Send only new logs
                new_logs = current_logs[last_log_count:]
                await manager.send_logs(flow_id, new_logs)
                last_log_count = len(current_logs)
            
            # Check if flow is completed or failed
            flow_status = agent_flow_manager.get_flow_status(flow_id)
            if flow_status in [FlowStatus.COMPLETED, FlowStatus.FAILED, FlowStatus.STOPPED]:
                await manager.send_status(flow_id, flow_status.value, True)
                break
                
    except WebSocketDisconnect:
        manager.disconnect(flow_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(flow_id)
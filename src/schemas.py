"""Pydantic schemas - consistent Excel output, evidence-based."""
from pydantic import BaseModel, Field
from typing import Literal

Quality = Literal["Good", "Partial", "Poor", "Unclear"]
Sentiment = Literal["satisfied", "dissatisfied", "neutral", "unclear"]
Resolution = Literal["resolved", "unresolved", "unclear"]

class ConversationAnalysis(BaseModel):
    conversation_id: int
    conversation_date: str = ""
    customer_name: str = ""
    mobile_number: str = ""
    agent_name: str = ""
    customer_message_count: int = 0
    bot_response_count: int = 0
    main_intent: str = ""
    customer_problem: str = ""
    english_summary: str = ""
    chatbot_understanding: Quality = "Unclear"
    response_quality: Quality = "Unclear"
    repetition_detected: str = "No"
    incorrect_irrelevant: str = "No"
    customer_sentiment: Sentiment = "unclear"
    resolution_status: Resolution = "unclear"
    main_failure: str = "None detected"
    evidence: str = ""
    recommended_improvement: str = ""

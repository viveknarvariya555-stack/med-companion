# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import os
import re
from typing import Any
from zoneinfo import ZoneInfo

from google.adk.agents import LlmAgent
from google.adk.apps import App, ResumabilityConfig
from google.adk.models import Gemini
from google.adk.tools import AgentTool, ToolContext
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from google.adk.workflow import Workflow, START, node
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.genai import types

from .config import config

# --- MCP Toolsets ---

mcp_safety_tools = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "app.mcp_server"]
        )
    ),
    tool_filter=["check_drug_interactions", "get_medication_guidelines"]
)

mcp_scheduler_tools = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "app.mcp_server"]
        )
    ),
    tool_filter=["log_medication_intake", "get_care_logs"]
)

# Path for Care Logs and Security Audit Logs
LOG_FILE = "/Users/viveknarvariya/Desktop/ADK.workspace/med-companion/care_logs.json"
AUDIT_LOG_FILE = "/Users/viveknarvariya/Desktop/ADK.workspace/med-companion/security_audit.log"

def write_audit_log(severity: str, event: str, details: str):
    """Writes a structured JSON audit log entry."""
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "severity": severity,
        "event": event,
        "details": details
    }
    try:
        with open(AUDIT_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

def write_care_log(drug: str, dose: str, time_taken: str):
    """Logs medication intake to care_logs.json."""
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f:
                logs = json.load(f)
        except Exception:
            pass
    logs.append({
        "drug": drug,
        "dose": dose,
        "time": time_taken,
        "logged_at": datetime.datetime.now().isoformat()
    })
    try:
        with open(LOG_FILE, "w") as f:
            json.dump(logs, f, indent=2)
    except Exception:
        pass

# --- Tools ---

def request_log_action(drug: str, dose: str, time: str, tool_context: ToolContext) -> dict:
    """Request to log a medication intake. This action will be queued for user confirmation.
    
    Args:
        drug: The name of the medication to log.
        dose: The dosage (e.g. 50mg, 1 tablet).
        time: The time the medication was taken (e.g. 9:00 AM, now).
    """
    tool_context.state["pending_action"] = {
        "action": "log",
        "drug": drug,
        "dose": dose,
        "time": time
    }
    return {
        "status": "pending_confirmation",
        "message": f"Queued request to log {dose} of {drug} at {time}. Awaiting user approval."
    }

# --- Specialized Agents ---

safety_agent = LlmAgent(
    name="safety_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are safety_agent, a specialized medical safety AI assistant. "
        "Your task is to analyze patients' medication queries for drug-drug interactions, "
        "side effects, dosage safety, and warning signs. "
        "Answer clearly, objectively, and highlight any potential warnings. "
        "Always remind the user to consult their doctor for clinical decisions."
    ),
    description="Analyzes medication queries for safety, side effects, and drug-drug interactions.",
    tools=[mcp_safety_tools]
)

scheduler_agent = LlmAgent(
    name="scheduler_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are scheduler_agent, a specialized medication scheduler and care logger AI assistant. "
        "Your job is to decipher medication schedules (e.g. 'twice a day') and assist users in logging "
        "their medication intake. "
        "If the user wants to log a medication intake, you MUST call the request_log_action tool with the drug, dose, and time. "
        "Never perform logging yourself without calling the tool."
    ),
    description="Manages medication scheduling, intake logs, and queries past care logs.",
    tools=[request_log_action, mcp_scheduler_tools]
)

# --- Orchestrator Agent ---

orchestrator = LlmAgent(
    name="orchestrator",
    model=Gemini(model=config.model),
    instruction=(
        "You are the Med-Companion orchestrator. Your job is to coordinate medical care requests. "
        "Use safety_agent for drug interactions, safety guidelines, and side effects. "
        "Use scheduler_agent for scheduling medications and logging medication intake. "
        "When delegation occurs, summarize the findings for the user clearly. "
        "If a sub-agent requests a logging action, make sure to report that the action is pending confirmation."
    ),
    tools=[AgentTool(safety_agent), AgentTool(scheduler_agent)]
)

# --- Workflow Nodes ---

def security_checkpoint(ctx: Context, node_input: types.Content) -> Event:
    """Security Checkpoint Node to scrub PII and prevent Prompt Injection."""
    # Get user prompt text
    query = ""
    if hasattr(node_input, "parts") and node_input.parts:
        query = "".join([p.text for p in node_input.parts if p.text])
    elif isinstance(node_input, str):
        query = node_input

    # 1. Prompt Injection Detection
    injection_patterns = [
        r"ignore\s+(?:previous|all)\s+instructions",
        r"system\s+prompt",
        r"you\s+are\s+now",
        r"jailbreak"
    ]
    for pattern in injection_patterns:
        if re.search(pattern, query, re.IGNORECASE):
            write_audit_log("CRITICAL", "PROMPT_INJECTION_DETECTED", f"Input: {query}")
            return Event(output="Prompt injection attempt detected.", route="security_event")

    # 2. PII Scrubbing
    scrubbed = query
    # Email pattern
    scrubbed, email_count = re.subn(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL_REDACTED]", scrubbed)
    # Phone pattern
    scrubbed, phone_count = re.subn(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "[PHONE_REDACTED]", scrubbed)
    # SSN pattern
    scrubbed, ssn_count = re.subn(r"\b\d{3}-\d{2}-\d{4}\b", "[SSN_REDACTED]", scrubbed)

    if email_count > 0 or phone_count > 0 or ssn_count > 0:
        write_audit_log("WARNING", "PII_REDACTED", f"Redacted: {email_count} emails, {phone_count} phones, {ssn_count} SSNs")
        # Update the content with the scrubbed version
        node_input = types.Content(role="user", parts=[types.Part.from_text(text=scrubbed)])

    # 3. Domain-specific Consent Check (Consent token simulation)
    if "consent" in query.lower() and "deny" in query.lower():
        write_audit_log("WARNING", "CONSENT_REVOKED", "User denied medical data processing consent.")
        return Event(output="You have denied consent for data processing. Actions are restricted.", route="security_event")

    write_audit_log("INFO", "INPUT_CLEARED", "Input passed all checks.")
    return Event(output=node_input, route="__DEFAULT__")

def router_node(ctx: Context, node_input: types.Content) -> Event:
    """Inspects session state to see if a logging action requires human approval."""
    pending = ctx.state.get("pending_action")
    if pending:
        return Event(output=node_input, route="requires_approval")
    return Event(output=node_input, route="__DEFAULT__")

async def hitl_approval(ctx: Context, node_input: types.Content):
    """Prompts the user for confirmation of sensitive logging actions."""
    if not ctx.resume_inputs or "approve_log" not in ctx.resume_inputs:
        pending = ctx.state.get("pending_action")
        msg = (
            f"✋ Med-Companion requires your approval to perform the following action:\n\n"
            f"  * **Action**: Log Medication Intake\n"
            f"  * **Medication**: {pending['drug']}\n"
            f"  * **Dosage**: {pending['dose']}\n"
            f"  * **Time**: {pending['time']}\n\n"
            f"Do you approve this action? (Please reply 'yes' or 'no')"
        )
        yield RequestInput(interrupt_id="approve_log", message=msg)
        return

    # Process response
    user_response = ctx.resume_inputs["approve_log"].strip().lower()
    pending = ctx.state.get("pending_action")
    
    if "yes" in user_response or "approve" in user_response:
        write_care_log(pending["drug"], pending["dose"], pending["time"])
        msg = f"✅ Action approved. Successfully logged intake: {pending['drug']} ({pending['dose']}) at {pending['time']}."
        ctx.state["pending_action"] = None
        yield Event(output=msg)
    else:
        msg = f"❌ Action denied. The medication logging request for {pending['drug']} was cancelled."
        ctx.state["pending_action"] = None
        yield Event(output=msg)

def security_event(ctx: Context, node_input: str):
    """Outputs security alert message."""
    yield Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=f"🚨 SECURITY WARNING: {node_input}")]
        ),
        output=f"🚨 SECURITY WARNING: {node_input}"
    )

def final_output(ctx: Context, node_input: Any):
    """Renders final output to the user interface."""
    output_text = ""
    if isinstance(node_input, str):
        output_text = node_input
    elif hasattr(node_input, "parts") and node_input.parts:
        output_text = "".join([p.text for p in node_input.parts if p.text])
    else:
        output_text = str(node_input)

    yield Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=output_text)]
        ),
        output=output_text
    )

# --- Workflow Setup ---

root_workflow = Workflow(
    name="med_companion_workflow",
    edges=[
        (START, security_checkpoint),
        (security_checkpoint, {"security_event": security_event, "__DEFAULT__": orchestrator}),
        (orchestrator, router_node),
        (router_node, {"requires_approval": hitl_approval, "__DEFAULT__": final_output}),
        (hitl_approval, final_output)
    ]
)

app = App(
    root_agent=root_workflow,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True)
)

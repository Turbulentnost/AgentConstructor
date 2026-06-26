"""Tool gateway and registry package."""

from agent_desktop_constructor.tools.base import BaseTool
from agent_desktop_constructor.tools.catalog import (
    ToolCatalogItem,
    ToolsCatalog,
    validate_agent_spec_tools_against_catalog,
)
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog
from agent_desktop_constructor.tools.com_backed_tools import (
    ComBackedTool,
    EmailCreateDraftComTool,
    EmailSendComTool,
    OutlookReadCalendarComTool,
    OutlookReadTasksComTool,
    OutlookSearchMailComTool,
    register_outlook_com_tools,
)
from agent_desktop_constructor.tools.fake_task_control_tools import (
    FakeEmailCreateDraftTool,
    FakeEmailSendTool,
    FakeOutlookReadCalendarTool,
    FakeOutlookReadTasksTool,
    FakeOutlookSearchMailTool,
    FakeReportBuildTaskReportTool,
    register_fake_task_control_tools,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry

__all__ = [
    "BaseTool",
    "ComBackedTool",
    "EmailCreateDraftComTool",
    "EmailSendComTool",
    "FakeEmailCreateDraftTool",
    "FakeEmailSendTool",
    "FakeOutlookReadCalendarTool",
    "FakeOutlookReadTasksTool",
    "FakeOutlookSearchMailTool",
    "FakeReportBuildTaskReportTool",
    "OutlookReadCalendarComTool",
    "OutlookReadTasksComTool",
    "OutlookSearchMailComTool",
    "ToolCatalogItem",
    "ToolGateway",
    "ToolRegistry",
    "ToolsCatalog",
    "register_fake_task_control_tools",
    "register_outlook_com_tools",
    "load_tools_catalog",
    "validate_agent_spec_tools_against_catalog",
]

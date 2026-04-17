"""
`get_nas_cause_meaning`: look up a 3GPP 5GMM / 5GSM cause code.

Backs the LLM's "what does cause 22 mean?" questions with a static,
profile-owned dictionary. The profile's knowledge base (`search_knowledge`)
carries the longer prose explanation; this tool just returns the short
name + category so the LLM doesn't have to parse markdown.
"""

from __future__ import annotations

from typing import Any

from traceweaver.core.tools.base import Tool, ToolContext, ToolResult, ToolSpec


# Subset covering the cause codes Open5GS actually emits in practice.
# The complete list is maintained in the profile's knowledge markdowns
# (5gmm_causes.md / 5gsm_causes.md) and can be looked up via
# `search_knowledge`.

_CAUSE_5GMM: dict[int, tuple[str, str]] = {
    3: ("Illegal UE", "identity"),
    5: ("PEI not accepted", "identity"),
    6: ("Illegal ME", "identity"),
    7: ("5GS services not allowed", "subscription"),
    9: ("UE identity cannot be derived by the network", "identity"),
    10: ("Implicitly de-registered", "mobility"),
    11: ("PLMN not allowed", "subscription"),
    12: ("Tracking area not allowed", "subscription"),
    13: ("Roaming not allowed in this tracking area", "subscription"),
    15: ("No suitable cells in tracking area", "radio"),
    20: ("MAC failure", "security"),
    21: ("Synch failure", "security"),
    22: ("Congestion", "capacity"),
    23: ("UE security capabilities mismatch", "security"),
    24: ("Security mode rejected, unspecified", "security"),
    27: ("N1 mode not allowed", "subscription"),
    28: ("Restricted service area", "subscription"),
    43: ("LADN not available", "feature"),
    65: ("Maximum number of PDU sessions reached", "capacity"),
    67: ("Insufficient resources for specific slice and DNN", "capacity"),
    69: ("Insufficient resources for specific slice", "capacity"),
    71: ("ngKSI already in use", "security"),
    72: ("Non-5G authentication unacceptable", "security"),
    73: ("N1 mode not allowed", "subscription"),
    74: ("Restricted new NSSAI", "subscription"),
    75: ("Serving network not authorized", "security"),
    80: ("Payload was not forwarded", "transport"),
    83: ("Semantically incorrect message", "protocol"),
    91: ("DNN not supported or not subscribed in the slice", "subscription"),
}


_CAUSE_5GSM: dict[int, tuple[str, str]] = {
    8: ("Operator determined barring", "subscription"),
    26: ("Insufficient resources", "capacity"),
    27: ("Missing or unknown DNN", "configuration"),
    28: ("Unknown PDU session type", "configuration"),
    29: ("User authentication or authorization failed", "security"),
    31: ("Request rejected, unspecified", "generic"),
    32: ("Service option not supported", "capability"),
    33: ("Requested service option not subscribed", "subscription"),
    35: ("PTI already in use", "protocol"),
    36: ("Regular deactivation", "normal"),
    38: ("Network failure", "infrastructure"),
    39: ("Reactivation requested", "normal"),
    41: ("Semantic error in the TFT operation", "protocol"),
    43: ("Invalid PDU session identity", "protocol"),
    44: ("Semantic errors in packet filter(s)", "protocol"),
    45: ("Syntactical error in packet filter(s)", "protocol"),
    46: ("Out of LADN service area", "feature"),
    50: ("PDU session type IPv4 only allowed", "configuration"),
    51: ("PDU session type IPv6 only allowed", "configuration"),
    54: ("PDU session does not exist", "state"),
    67: ("Insufficient resources for specific slice and DNN", "capacity"),
    68: ("Not supported SSC mode", "capability"),
    69: ("Insufficient resources for specific slice", "capacity"),
    70: ("Missing or unknown DNN in a slice", "configuration"),
    71: ("Invalid PTI value", "protocol"),
    72: ("Maximum data rate per UE for user-plane integrity protection is too low", "security"),
    73: ("Semantic error in the QoS operation", "protocol"),
    74: ("Syntactical error in the QoS operation", "protocol"),
    83: ("Semantically incorrect message", "protocol"),
    95: ("Protocol error, unspecified", "protocol"),
    100: ("5GSM cause #100 (not in catalog)", "unknown"),
}


class GetNasCauseMeaningTool(Tool):
    spec = ToolSpec(
        name="get_nas_cause_meaning",
        description=(
            "Translate a 5GMM or 5GSM cause code to a human-readable "
            "name and category. Provide the integer `code` and the "
            "`layer` ('5gmm' or '5gsm'). Returns "
            "`{code, layer, name, category}`. Call `search_knowledge` "
            "for the full paragraph-long explanation."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "code": {"type": "integer"},
                "layer": {
                    "type": "string",
                    "enum": ["5gmm", "5gsm"],
                    "description": "Which NAS layer the cause belongs to.",
                },
            },
            "required": ["code", "layer"],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        try:
            code = int(kwargs.get("code"))
        except (TypeError, ValueError):
            return ToolResult(
                data={"hint": "code must be an integer; e.g. 22 for 5GMM Congestion."},
            )
        layer = str(kwargs.get("layer") or "").lower()
        if layer not in ("5gmm", "5gsm"):
            return ToolResult(
                data={"hint": "layer must be '5gmm' or '5gsm'."},
            )

        table = _CAUSE_5GMM if layer == "5gmm" else _CAUSE_5GSM
        hit = table.get(code)
        if hit is None:
            return ToolResult(
                data={
                    "code": code,
                    "layer": layer,
                    "hint": (
                        f"cause #{code} is not in the {layer.upper()} "
                        "short-name catalog; call search_knowledge with "
                        "the code for the full explanation."
                    ),
                },
            )
        name, category = hit
        return ToolResult(
            data={
                "code": code,
                "layer": layer,
                "name": name,
                "category": category,
            }
        )


__all__ = ["GetNasCauseMeaningTool"]

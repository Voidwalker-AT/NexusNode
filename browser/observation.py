"""
NexusNode — Bounded Page Observation & Semantic Element Reference System
Transforms raw CDP DOM / Accessibility trees into structured, token-efficient,
LLM-ready observations bounded to <= 50 KB with monotonic epoch and stale ref protection.
"""

import time
import json
import uuid
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

from .base import BrowserElement, BrowserSnapshot

logger = logging.getLogger("NEXUS_BROWSER_OBSERVATION")

MAX_OBSERVATION_BYTES = 50 * 1024  # 50 KB hard budget


class ElementStaleError(Exception):
    """Raised when an action attempts to interact with an element from a prior epoch."""
    pass


@dataclass
class ObservationElement:
    ref_id: str                      # e.g. 'e0', 'e1'
    epoch: int                       # Observation epoch when generated
    node_id: int                     # CDP DOM Node ID
    backend_node_id: Optional[int]   # CDP Backend Node ID
    role: str                        # e.g. 'button', 'textbox', 'link', 'combobox'
    name: str                        # Accessible name or label
    value: str = ""                  # Value / text / state
    tag_name: str = ""
    is_clickable: bool = True
    is_editable: bool = False
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_browser_element(self) -> BrowserElement:
        return BrowserElement(
            ref_id=self.ref_id,
            tag_name=self.tag_name,
            role=self.role,
            name=self.name,
            is_clickable=self.is_clickable,
            is_editable=self.is_editable,
            attributes=self.attributes
        )


@dataclass
class BrowserObservation:
    observation_id: str
    epoch: int
    url: str
    title: str
    headings: List[Dict[str, Any]] = field(default_factory=list)
    elements: List[ObservationElement] = field(default_factory=list)
    text_excerpt: str = ""
    tree_text: str = ""
    screenshot_base64: Optional[str] = None
    token_estimate: int = 0
    timestamp: float = field(default_factory=time.time)
    content_type: str = "untrusted_web_content"

    def to_envelope(self) -> str:
        """Wraps observation in untrusted web content boundary for LLM agents."""
        return (
            f'<untrusted_web_content origin="{self.url}" epoch="{self.epoch}" id="{self.observation_id}" timestamp="{self.timestamp:.0f}">\n'
            f'  <page_title>{self.title}</page_title>\n'
            f'  <accessibility_tree>\n'
            f'{self.tree_text}\n'
            f'  </accessibility_tree>\n'
            f'</untrusted_web_content>'
        )

    def to_snapshot(self) -> BrowserSnapshot:
        elem_map = {el.ref_id: f"[{el.role}] {el.name}" for el in self.elements}
        return BrowserSnapshot(
            url=self.url,
            title=self.title,
            tree_text=self.tree_text,
            element_map=elem_map,
            screenshot_base64=self.screenshot_base64,
            token_estimate=self.token_estimate,
            timestamp=self.timestamp
        )


class ObservationRegistry:
    """
    Maintains active observation epochs and element caches per session.
    Validates element references against the active epoch to guarantee stale-ref rejection.
    """

    def __init__(self):
        # session_id -> {
        #   "current_epoch": int,
        #   "current_observation_id": str,
        #   "elements": {ref_id: ObservationElement}
        # }
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def init_session(self, session_id: str):
        self._sessions[session_id] = {
            "current_epoch": 0,
            "current_observation_id": "",
            "elements": {}
        }

    def clear_session(self, session_id: str):
        self._sessions.pop(session_id, None)

    def advance_epoch(self, session_id: str) -> int:
        """Called when a navigation, reload, or major DOM mutation occurs."""
        sess = self._sessions.setdefault(session_id, {
            "current_epoch": 0,
            "current_observation_id": "",
            "elements": {}
        })
        sess["current_epoch"] += 1
        sess["elements"].clear()
        return sess["current_epoch"]

    def register_observation(self, session_id: str, observation: BrowserObservation):
        sess = self._sessions.setdefault(session_id, {
            "current_epoch": 0,
            "current_observation_id": "",
            "elements": {}
        })
        sess["current_epoch"] = observation.epoch
        sess["current_observation_id"] = observation.observation_id
        sess["elements"] = {el.ref_id: el for el in observation.elements}

    def resolve_ref(self, session_id: str, element_ref: str) -> ObservationElement:
        sess = self._sessions.get(session_id)
        if not sess:
            raise ElementStaleError(f"Session '{session_id}' not found in observation registry.")

        elem = sess["elements"].get(element_ref)
        if not elem:
            raise ElementStaleError(
                f"Element '{element_ref}' is stale or does not exist in active epoch {sess['current_epoch']}."
            )

        if elem.epoch != sess["current_epoch"]:
            raise ElementStaleError(
                f"Element '{element_ref}' belongs to epoch {elem.epoch}, but active epoch is {sess['current_epoch']}."
            )

        return elem


# ==============================================================================
# Accessibility Tree Processor & Size Clamping
# ==============================================================================

INTERACTIVE_ROLES = {
    "button", "link", "heading", "textbox", "searchbox", "checkbox", "radio",
    "combobox", "menuitem", "tab", "alert", "dialog", "form", "switch",
    "option", "RootWebArea"
}

HIGH_PRIORITY_ROLES = {
    "button", "textbox", "searchbox", "combobox", "checkbox", "radio", "link", "form"
}


def build_bounded_observation(
    raw_ax_nodes: List[Dict[str, Any]],
    url: str,
    title: str,
    epoch: int,
    screenshot_b64: Optional[str] = None
) -> BrowserObservation:
    """
    Transforms raw CDP accessibility nodes into a normalized, budget-constrained BrowserObservation.
    Enforces <= 50 KB payload budget.
    """
    obs_id = f"obs_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
    elements: List[ObservationElement] = []
    headings: List[Dict[str, Any]] = []
    text_fragments: List[str] = []

    ref_counter = 0

    for node in raw_ax_nodes:
        role_val = node.get("role", {}).get("value", "") if isinstance(node.get("role"), dict) else node.get("role", "")
        name_val = node.get("name", {}).get("value", "") if isinstance(node.get("name"), dict) else node.get("name", "")
        value_val = node.get("value", {}).get("value", "") if isinstance(node.get("value"), dict) else node.get("value", "")
        node_id = node.get("nodeId", 0)
        backend_node_id = node.get("backendDOMNodeId")

        name_str = (str(name_val) if name_val is not None else "").strip()
        role_str = (str(role_val) if role_val is not None else "").strip()
        value_str = (str(value_val) if value_val is not None else "").strip()

        # Capture headings
        if role_str == "heading" and name_str:
            level = 1
            for prop in node.get("properties", []):
                if prop.get("name") == "level":
                    level = prop.get("value", {}).get("value", 1)
            headings.append({"level": level, "text": name_str})

        # Capture text excerpts
        if role_str in ("StaticText", "paragraph") and name_str:
            text_fragments.append(name_str)

        # Include relevant elements
        if role_str in INTERACTIVE_ROLES or (name_str and role_str not in ("GenericContainer", "none", "ignored")):
            ref_id = f"e{ref_counter}"
            ref_counter += 1

            is_clickable = role_str in ("button", "link", "checkbox", "radio", "tab", "menuitem")
            is_editable = role_str in ("textbox", "searchbox", "combobox")

            obs_el = ObservationElement(
                ref_id=ref_id,
                epoch=epoch,
                node_id=node_id,
                backend_node_id=backend_node_id,
                role=role_str,
                name=name_str,
                value=value_str,
                is_clickable=is_clickable,
                is_editable=is_editable
            )
            elements.append(obs_el)

    # Build accessibility tree text lines
    lines: List[str] = []
    for el in elements:
        val_suffix = f' value="{el.value}"' if el.value else ""
        lines.append(f'[{el.ref_id}] {el.role}: "{el.name}"{val_suffix}')

    tree_text = "\n".join(lines)
    full_text_excerpt = "\n".join(text_fragments[:20])

    # Check size against 50 KB budget
    approx_size = len(tree_text.encode("utf-8")) + len(full_text_excerpt.encode("utf-8"))
    if approx_size > MAX_OBSERVATION_BYTES:
        logger.info(f"Observation exceeds 50 KB ({approx_size} B). Pruning lower-priority elements.")
        pruned_lines: List[str] = []
        pruned_elements: List[ObservationElement] = []

        # Keep high-priority interactive roles first
        for el in elements:
            if el.role in HIGH_PRIORITY_ROLES or len(pruned_lines) < 150:
                val_suffix = f' value="{el.value}"' if el.value else ""
                line = f'[{el.ref_id}] {el.role}: "{el.name}"{val_suffix}'
                if sum(len(l.encode("utf-8")) + 1 for l in pruned_lines) + len(line.encode("utf-8")) < (MAX_OBSERVATION_BYTES - 2048):
                    pruned_lines.append(line)
                    pruned_elements.append(el)
                else:
                    break

        tree_text = "\n".join(pruned_lines)
        elements = pruned_elements
        full_text_excerpt = full_text_excerpt[:1024]

    token_estimate = len(tree_text.split()) + len(full_text_excerpt.split()) + 50

    return BrowserObservation(
        observation_id=obs_id,
        epoch=epoch,
        url=url,
        title=title,
        headings=headings,
        elements=elements,
        text_excerpt=full_text_excerpt,
        tree_text=tree_text,
        screenshot_base64=screenshot_b64,
        token_estimate=token_estimate
    )

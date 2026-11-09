"""Event-derived conversation state for one session.

Live state mutations emit facts and use the same apply_event reducer as replay.
Store persists the facts and caches state snapshots. Agent resources and database
revisions are injected separately; replay never performs external operations.
"""

import json
import re
import logging
from copy import deepcopy
from typing import Text, List, Dict, Any, Optional, TYPE_CHECKING

from cota.events import Event, EventType

if TYPE_CHECKING:
    from cota.agent import Agent
    from cota.executor.user_memory import UserMemory

logger = logging.getLogger(__name__)
_UNSET = object()


class DST:
    """Dialogue State Tracker — tracks all state for one conversation session."""

    def __init__(
        self,
        session_id: Text,
        agent: "Agent",
        user_id: Optional[Text] = None,
    ) -> None:
        self.session_id = session_id
        self.agent = agent

        self._user_id = None
        self._events: List[Event] = []
        self._latest_user_event = None
        self._latest_bot_event = None
        self._user_context = {}
        self._active_skill = None
        self._execution = {}
        self._context_messages = []
        self._created_at = None
        self._updated_at = None
        # Store metadata, not conversation state. Never used by the reducer.
        self.revision = 0
        self._run_metadata = {}
        if user_id is not None:
            self.user_id = user_id

    @property
    def events(self):
        from cota.events.history import EventHistory
        return EventHistory(self._events)

    @property
    def run_metadata(self):
        """Immutable resource provenance, not event-derived conversation state."""
        return deepcopy(self._run_metadata)

    def record_run_skills(self, run_id, names, *, discovery=None, deploy=None, environment=None, native_tools=None):
        from cota.run_metadata import validate_run_metadata
        if not isinstance(names, list) or any(not isinstance(n, str) or not n.strip() for n in names):
            raise ValueError('Skill names must be a list of nonempty strings')
        data = {'available_skills': sorted(set(names))}
        if deploy is not None:
            data['deploy'] = deploy
        if discovery is not None:
            data['discovery'] = discovery
        if environment is not None:
            data['environment'] = environment
        if native_tools is not None:
            data['native_tools'] = native_tools
        candidate = validate_run_metadata({run_id: data}, self._events)
        if run_id in self._run_metadata and self._run_metadata[run_id] != data:
            raise ValueError('Run metadata is immutable')
        self._run_metadata.update(candidate)

    @property
    def latest_user_event(self):
        return deepcopy(self._latest_user_event)

    @property
    def latest_bot_event(self):
        return deepcopy(self._latest_bot_event)

    @property
    def created_at(self):
        return self._created_at

    @property
    def updated_at(self):
        return self._updated_at

    @property
    def user_id(self):
        return self._user_id

    @user_id.setter
    def user_id(self, value):
        if value != self._user_id:
            self.update_user(value, {})

    @property
    def active_skill(self):
        return self._active_skill

    @property
    def execution(self):
        return deepcopy(self._execution)

    @property
    def context_messages(self):
        """Derived conversation context; current request instructions are not persisted here."""
        return deepcopy(self._context_messages)

    def append_event(self, event: Event) -> None:
        """Complete live-event metadata, then use exactly the replay reducer."""
        if event.type != EventType.USER_UTTER and event.run_id is None:
            event.run_id = self._execution.get('run_id')
        self.apply_event(event)

    def _validate_transition(self, event):
        current = self._execution.get('run_id')
        status = self._execution.get('status')
        if event.type == EventType.RUN_STARTED:
            if not event.run_id or any(e.run_id == event.run_id for e in self._events):
                raise ValueError('run_started requires a new, nonempty run_id')
            if status == 'running':
                raise ValueError('Current execution is still running')
        elif event.type == EventType.RUN_FINISHED and event.run_id == current:
            correction = event.payload['status'] in ('failed', 'interrupted') and event.payload.get('error_type')
            if status not in (None, 'running') and not correction:
                raise ValueError('Current run is already finished')

    def apply_event(self, event: Event) -> None:
        """Apply one fact, in sequence, without I/O or emitting more events.

        Both live execution and replay enter here. Event.timestamp is retained;
        replay never reads the wall clock, calls tools or refreshes user memory.
        """
        event.validate()
        if any(e.event_id == event.event_id for e in self._events):
            raise ValueError(f'duplicate event_id: {event.event_id}')
        expected = len(self._events) + 1
        if event.sequence not in (None, 0, expected):
            raise ValueError(f'Expected event sequence {expected}')
        from cota.trace import validate_event_references
        validate_event_references(event, self._events)
        self._validate_transition(event)
        event.sequence = expected
        # Detach from the producer so it cannot mutate applied state by aliasing.
        fact = Event.from_dict(event.as_dict())
        p, kind = fact.payload, fact.type
        current_run = self._execution.get('run_id')
        # Late/foreign run observations are facts for Trace, never commands to
        # the currently executing run. Unbound observations are also trace-only.
        projects_execution = current_run is not None and fact.run_id == current_run
        running = self._execution.get('status') in (None, 'running')
        projects_tool = projects_execution and running
        from cota.events.context import apply_context
        trigger_event = next((e for e in self._events if e.event_id == p.get('input_event_id')), None) if kind == EventType.RUN_STARTED else None
        deferred_ids = set()
        if kind == EventType.RUN_STARTED and (p.get('mode') == 'group' or p.get('context_input_id')):
            cutoff_id = p.get('context_input_id', p['input_event_id'])
            cutoff = next(e.sequence for e in self._events if e.event_id == cutoff_id)
            deferred_ids = {e.event_id for e in self._events
                            if e.type == EventType.USER_UTTER and e.sequence > cutoff}
        context = apply_context(self._context_messages, fact, active_run=current_run if running else None,
                                trigger_event=trigger_event, deferred_input_ids=deferred_ids)
        if kind == EventType.USER_CONTEXT_UPDATED:
            self._user_id = p['user_id']
            self._user_context = deepcopy(p['context'])
        elif kind == EventType.RUN_STARTED:
            self._execution = {
                'engine': p.get('engine', 'pi'), 'engine_version': p.get('engine_version'),
                'run_id': fact.run_id, 'status': 'running',
                'input_event_id': p.get('input_event_id'),
                **({key: p[key] for key in ('mode', 'reason', 'context_through', 'context_input_id') if key in p}),
                'pending_tools': {},
            }
        elif kind == EventType.RUN_FINISHED and projects_execution:
            self._execution['status'] = p['status']
            for key in ('error_type',):
                if key in p:
                    self._execution[key] = deepcopy(p[key])
        elif kind == EventType.TOOL_STARTED and projects_tool:
            self._execution.setdefault('pending_tools', {})[p['tool_call_id']] = {
                'name': p['tool'], 'arguments': deepcopy(p['arguments'])}
        elif kind == EventType.TOOL_RESULT and projects_tool:
            self._execution.setdefault('pending_tools', {}).pop(p['tool_call_id'], None)
            from cota.events.resources import skill_read_name
            skill = skill_read_name(fact)
            if skill:
                self._active_skill = skill
        elif kind == EventType.USER_UTTER:
            self._latest_user_event = fact
        elif kind == EventType.BOT_UTTER:
            self._latest_bot_event = fact
        self._context_messages = context
        self._events.append(fact)
        if self._created_at is None:
            self._created_at = fact.timestamp
        self._updated_at = fact.timestamp

    def trace(self, run_id: str) -> Dict[str, Any]:
        from cota.trace import build_trace
        return build_trace(self._events, run_id)

    def latest_user_text(self) -> str:
        if self._latest_user_event:
            return self._latest_user_event.text
        return ""

    def latest_bot_text(self) -> str:
        if self._latest_bot_event:
            return self._latest_bot_event.text
        return ""

    # ------------------------------------------------------------------
    # User context (from UserMemory)
    # ------------------------------------------------------------------

    def update_user(self, user_id, context) -> None:
        """Atomically replace identity and its memory; unchanged pairs emit nothing."""
        from cota.executor.user_memory import RESERVED_MEMORY_KEYS
        if isinstance(context, dict):
            context = {key: value for key, value in context.items() if key not in RESERVED_MEMORY_KEYS}
        event = Event(EventType.USER_CONTEXT_UPDATED, {'user_id': user_id, 'context': context})
        previous = {'user_id': self._user_id, 'context': self._user_context}
        if json.dumps(event.payload, sort_keys=True, allow_nan=False) != json.dumps(previous, sort_keys=True, allow_nan=False):
            self.append_event(event)

    def load_user_context(self, user_memory: "UserMemory", *, user_id=_UNSET) -> None:
        """Refresh before new input, recording identity and memory in one fact.

        A failed refresh keeps only this user's previous memory. Switching users
        never inherits the old user's preferences, including when memory is offline.
        """
        target = self.user_id if user_id is _UNSET else user_id
        context = self.user_context if target == self.user_id else {}
        if target and user_memory is not None:
            try:
                loaded = user_memory.get_all(target)
                # Validate the complete pair before replacing the previous context.
                Event(EventType.USER_CONTEXT_UPDATED, {'user_id': target, 'context': loaded})
                context = loaded
            except Exception as error:
                logger.warning('Failed to load user context for %s (%s)', target, type(error).__name__)
        self.update_user(target, context)

    @property
    def user_context(self) -> Dict[str, Any]:
        return deepcopy(self._user_context)

    def get_user_pref(self, key: str, default: Any = None) -> Any:
        return deepcopy(self._user_context.get(key, default))

    # ------------------------------------------------------------------
    # Serialization — events are stored as-is (no compression)
    # ------------------------------------------------------------------

    STATE_VERSION = 11

    def state_dict(self):
        """Only deterministic state: no history, agent or database revision."""
        return deepcopy({
            'user_id': self._user_id, 'user_context': self._user_context,
            'active_skill': self._active_skill,
            'execution': self._execution,
            'context_messages': self._context_messages,
            'created_at': self._created_at, 'updated_at': self._updated_at,
            'latest_user_event_id': self._latest_user_event.event_id if self._latest_user_event else None,
            'latest_bot_event_id': self._latest_bot_event.event_id if self._latest_bot_event else None,
        })

    @staticmethod
    def _facts(events):
        from cota.trace import validate_event_references
        facts, identities = [], set()
        for index, raw in enumerate(events, 1):
            event = Event.from_dict(raw.as_dict() if isinstance(raw, Event) else raw)
            if event.event_id in identities:
                raise ValueError('duplicate event_id in persisted history')
            if type(event.sequence) is not int or event.sequence != index:
                raise ValueError('Invalid event sequence in persisted history')
            validate_event_references(event, facts)
            identities.add(event.event_id)
            facts.append(event)
        return facts

    def as_dict(self) -> Dict[Text, Any]:
        from cota.run_metadata import validate_run_metadata
        metadata = validate_run_metadata(self._run_metadata, self._events)
        facts = self._facts(self._events)
        state = self.state_dict()
        # Full detached export for existing history/trace consumers; Store does
        # not persist this document. Physical snapshots contain state_dict only.
        result = {'session_id': self.session_id,
                  'run_metadata': metadata,
                  'revision': self.revision, 'events': [e.as_dict() for e in facts],
                  **state}
        return result

    @classmethod
    def from_events(cls, session_id, events, agent=None, *, snapshot=None, revision=0, run_metadata=None):
        from cota.run_metadata import validate_run_metadata
        metadata = validate_run_metadata(run_metadata if run_metadata is not None else {}, events)
        facts = cls._facts(events)
        tracker = cls(session_id, agent)
        tracker._run_metadata = metadata
        start = 0
        if snapshot is not None:
            from cota.snapshots import usable_snapshot
            if usable_snapshot(snapshot, session_id, facts):
                start = snapshot['last_sequence']
                state = deepcopy(snapshot['state'])
                tracker._events = facts[:start]
                for name in ('user_id', 'user_context', 'active_skill', 'execution', 'context_messages'):
                    setattr(tracker, '_' + name, state[name])
                tracker._created_at, tracker._updated_at = state['created_at'], state['updated_at']
                by_id = {event.event_id: event for event in tracker._events}
                tracker._latest_user_event = by_id.get(state['latest_user_event_id'])
                tracker._latest_bot_event = by_id.get(state['latest_bot_event_id'])
        for event in facts[start:]:
            tracker.apply_event(event)
        tracker.revision = revision
        return tracker

    @staticmethod
    def _user_content(event):
        from cota.events.context import user_content
        return user_content(event) if event.type == EventType.USER_UTTER else event.text

    def build_history_messages(self) -> List[Dict[str, Any]]:
        """Return business messages, excluding the last user query.

        Full tool history belongs to ``context_messages``. Skill reads and
        tool audit events must not synthesize assistant responses here.
        """
        last_user_idx = next(
            (i for i in range(len(self._events) - 1, -1, -1)
             if self._events[i].type == EventType.USER_UTTER),
            -1,
        )
        messages: List[Dict[str, Any]] = []
        for idx, event in enumerate(self._events):
            if event.type == EventType.USER_UTTER and idx != last_user_idx:
                messages.append({"role": "user", "content": self._user_content(event)})
            elif event.type == EventType.BOT_UTTER:
                messages.append({"role": "assistant", "content": self._user_content(event)})
        return messages

    def extract_messages(self) -> List[Dict[Text, Any]]:
        """Extract user/bot messages for LLM context (e.g. RAG, knowledge)."""
        messages = []
        for e in self._events:
            if e.type == EventType.USER_UTTER:
                messages.append({"role": "user", "content": self._user_content(e)})
            elif e.type == EventType.BOT_UTTER:
                messages.append({"role": "assistant", "content": e.text})
        return messages

    # ------------------------------------------------------------------
    # Prompt formatting
    # ------------------------------------------------------------------

    def format_prompt(self, prompt: Text, append: Optional[Dict] = None) -> Text:
        if append:
            for key, value in append.items():
                prompt = prompt.replace("{{" + key + "}}", value)

        variable_names = re.findall(r"\{\{(\w+)\}\}", prompt)
        format_dict = {
            var_name: self.observe(var_name)
            for var_name in variable_names
        }
        for key in format_dict:
            prompt = prompt.replace("{{" + key + "}}", format_dict[key])
        return prompt


    async def format_knowledge(self, prompt: Text, *, query=None) -> Dict[str, str]:
        knowledge_variables = re.findall(r"\{\{(knowledge)\}\}", prompt)
        if not knowledge_variables:
            return {}
        knowledge = getattr(self.agent, "knowledge", None)
        if not knowledge:
            return {}
        try:
            query = self.latest_user_text() if query is None else query
            content = await knowledge.process_query(
                query=query,
                context={"dst": self, "agent": self.agent},
            )
            return {"knowledge": content or ""}
        except Exception as e:
            logger.error(f"Knowledge retrieval failed: {e}")
            return {"knowledge": ""}


    # ------------------------------------------------------------------
    # Observe methods (for prompt template variables)
    # ------------------------------------------------------------------

    _ALLOWED_OBSERVE_METHODS = {
        "task_description",
        "agent_description",
        "user_context_text",
        "session_summary",
        "latest_user_query",
        "compressed_history",
        "history_messages",
    }

    def observe(self, name):
        if name not in self._ALLOWED_OBSERVE_METHODS:
            logger.warning(
                f"Prompt variable '{{{{{name}}}}}' is not recognized; "
                f"returning empty string. Migrate your prompt template."
            )
            return ""
        method = getattr(self, name)
        return method()

    def task_description(self):
        return self.agent.description or ""

    def agent_description(self):
        return self.agent.description or ""

    def latest_user_query(self):
        return self.latest_user_text()

    def user_context_text(self) -> str:
        from cota.executor.user_memory import RESERVED_MEMORY_KEYS
        if not self._user_context:
            return ""
        lines = []
        for k, v in self._user_context.items():
            if k in RESERVED_MEMORY_KEYS:
                continue
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def session_summary(self) -> str:
        parts = []
        if self.user_id:
            parts.append(f"user: {self.user_id}")
        parts.append(f"messages: {sum(e.type in (EventType.USER_UTTER, EventType.BOT_UTTER) for e in self._events)}")
        return " | ".join(parts)

    def compressed_history(self) -> str:
        """Format user and bot history without synthesizing tool responses."""
        return "\n".join(
            f"{'user' if event.type == EventType.USER_UTTER else 'bot'}: {event.text}"
            for event in self._events
            if event.type in (EventType.USER_UTTER, EventType.BOT_UTTER)
        )

    def history_messages(self) -> str:
        """Format business-message history for prompt templates."""
        return self.compressed_history()

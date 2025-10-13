import json
import re
from collections import deque
from typing import Text, List, Dict, Any, Optional, Union, Tuple
from cota.actions.action import Action
from cota.constant import DEFAULT_DIALOGUE_MAX_TOKENS


class DST:
    """Dialogue State Tracker"""

    def __init__(
            self,
            session_id: Text,
            agent: 'Agent'
    ) -> None:
        """init tracker"""
        self.session_id = session_id
        self.agent = agent
        self.slots = {}
        self.actions = deque([])
        self.formless_actions = deque([])
        self.latest_action = None
        self.current_form = None
        self.latest_query = None
        self.latest_response = None
        self.latest_sender_id = None
        self.latest_receiver_id = None

    def update_actions(self, actions: List[Action]) -> None:
        for action in actions:
            self.update(action)

    def update(self, action: Action) -> None:
        """Update dialogue state with new action.
        
        Args:
            action: Single Action
        """
        # Apply the single action directly
        action.apply_to(self)

    def get_latest_query(self):
        return self.latest_query

    def current_state(self):
        # All actions are single actions now
        actions = [action.as_dict() for action in self.actions]
        return {
            "session_id": self.session_id,
            "slots": self.slots,
            "actions": actions
        }

    def extract_messages(self) -> List[Dict[Text, Any]]:
        from cota.actions.user_utter import UserUtter
        from cota.actions.bot_utter import BotUtter

        messages = []
        for action in self.actions:
            # All actions are single actions now
            if isinstance(action, UserUtter):
                for message in action.result:
                    messages.append({
                        'role': 'user',
                        'content': message.get('text','')
                    })
            elif isinstance(action, BotUtter):
                for message in action.result:
                    messages.append({
                        'role': 'assistant',
                        'content': message.get('text','')
                    })
        return messages

    def as_dict(self) -> Dict[Text, Any]:
        # All actions are single actions now
        actions = [action.as_dict() for action in self.actions]
        return {
            "session_id": self.session_id,
            "slots": self.slots,
            "actions": actions,
        }

    @classmethod
    def from_dict(
            cls,
            dst_dict: Dict[Text, Any],
            agent
    ) -> "DST":
        """Generate DST from action list dict"""
        actions = list()
        for action_dict in dst_dict.get("actions"):
            action = agent.build_action(action_dict.get("name"))
            action.run_from_dict(action_dict)
            actions.append(action)
        return cls.from_actions(dst_dict.get("session_id"), actions, agent)

    @classmethod
    def from_actions(
            cls,
            session_id: Text,
            actions: List[Action],
            agent
    ) -> "DST":
        tracker = cls(session_id, agent=agent)
        tracker.update_actions(actions=actions)
        return tracker

    def format_prompt(self, prompt: Text, action, append: Optional[Dict]=None) -> Text:
        if append:
            for key, value in append.items():
                prompt = prompt.replace('{{' + key + '}}', value)

        variable_names = re.findall(r'\{\{(\w+)\}\}', prompt)
        format_dict = {var_name: self.observe(var_name,action) for var_name in variable_names}
        for key in format_dict:
            prompt = prompt.replace('{{' + key + '}}', format_dict[key])
        return prompt

    async def format_rag(self, prompt: Text, action):
        variable_names = re.findall(r'\{\{(\w+)\}\}', prompt)
        if 'rag' in variable_names:
            rag_content = await self.agent.llm_instance(action.llm).generate_chat(
                messages = self.extract_messages(),
                max_tokens=self.agent.dialogue.get('max_tokens', DEFAULT_DIALOGUE_MAX_TOKENS)
            )
            return {'rag': rag_content["content"]}
        return {}

    async def format_thoughts(self, prompt: Text, action):
        """Format thoughts for the prompt by trying dialogue policy instances in priority order.
        
        Args:
            prompt: The prompt template text
            action: The current action
            
        Returns:
            Dict containing thoughts if {{thoughts}} is in prompt, empty dict otherwise
            
        Notes:
            - Only checks for thoughts if {{thoughts}} appears in prompt template
            - Tries each dialogue policy in order until first valid thought is found
            - Returns empty string for thoughts if no policy generates valid thoughts
        """
        variable_names = re.findall(r'\{\{(\w+)\}\}', prompt)
        if 'thoughts' in variable_names:
            thoughts_content = None
            # Try dialogue policies in priority order until we get a valid thought
            for dpl_instance in self.agent.dpl:
                thoughts = await dpl_instance.generate_thoughts(self, action)
                thoughts_content = thoughts
            return {'thoughts': thoughts_content or ''}
        return {}


    def observe(self, name, action):
        if hasattr(self, name):
            method = getattr(self, name)
            return method(action)
        else:
            raise AttributeError(f"Method {name} not found")

    def current_action_name(self, action: Action = None):
        return action.name

    def current_action_description(self, action: Action = None):
        return action.description

    def latest_action_name(self, action: Action = None):
        if self.latest_action:
            return self.latest_action.name
        return ""

    def latest_action_result(self, action: Action = None):
        if self.latest_action:
            return '\n'.join([ result.get('text', '') for result in self.latest_action.result])
        return ""

    def latest_action_description(self, action: Action = None):
        if self.latest_action:
            return self.latest_action.description
        return ""

    def latest_action_state(self, action: Action = None):
        from cota.actions.form import Form
        
        if self.latest_action:
            # If it's a Form type, output slots values
            if isinstance(self.latest_action, Form):
                return json.dumps(self.latest_action.slots, ensure_ascii=False)
            else:
                # If not Form, output empty object
                return "{}"
        return "{}"

    def latest_user_query(self, action: Action = None):
        return '\n'.join([message.get('text','') for message in self.latest_query.result])

    def action_names(self, action:Action = None):
        """all action names"""
        return ','.join([action for action in self.agent.actions])

    def action_descriptions(self, action:Action = None):
        """all action names with descriptions formatted for prompts"""
        descriptions = []
        
        for action_name, action_config in self.agent.actions.items():
             # Selector is not an option
            if action_name in ('Selector'):
                continue
            # Get description
            description = action_config.get("description", "")
            action_line = f"- `{action_name}`: {description}"
            descriptions.append(action_line)
            
            # Handle slots parameters
            slots = action_config.get("slots", {})
            if slots:
                # Build parameter dictionary, using slot description as example value
                slot_dict = {}
                for slot_name, slot_config in slots.items():
                    slot_description = slot_config.get("description", "")
                    slot_dict[slot_name] = slot_description
                
                # Format as JSON string
                slot_json = json.dumps(slot_dict, ensure_ascii=False)
                param_line = f"  - Parameters: `{slot_json}`"
            else:
                # Case with no slots
                param_line = "  - Parameters: `{}`"
            
            descriptions.append(param_line)
            descriptions.append("")  # Add blank line separator
        
        # Remove the last blank line
        if descriptions and descriptions[-1] == "":
            descriptions.pop()
            
        return '\n'.join(descriptions)

    def history_messages(self, action: Action = None) -> str:
        """Extract and format all historical messages with sender IDs.
        
        Returns:
            A string with all messages in format "sender_id:message_text", 
            separated by newlines.
        """
        from cota.actions.user_utter import UserUtter
        from cota.actions.bot_utter import BotUtter

        messages = []
        for action in self.actions:
            # All actions are single actions now
            if isinstance(action, (UserUtter, BotUtter)):
                messages.extend([
                    f"{message.get('sender_id', '')}:{message.get('text', '')}"
                    for message in action.result
                ])
                    
        return '\n'.join(messages)

    def history_actions(self, action:Action = None):
        from cota.actions.user_utter import UserUtter
        from cota.actions.bot_utter import BotUtter
        from cota.actions.form import Form

        actions = []
        for action in self.actions:
            if action.name not in ('Selector'):
                for result in action.result:
                    if len(result.get('text','')) > 0:
                        # Check if action has slots and display them
                        if isinstance(action, Form) and hasattr(action, 'slots') and action.slots:
                            slot_json = json.dumps(action.slots, ensure_ascii=False)
                            actions.append(f"{action.name}({slot_json}):{result.get('text','')}")
                        else:
                            actions.append(action.name + ':' + result.get('text',''))
        return '\n'.join(actions)

    def history_actions_with_thoughts(self, action: Action = None):
        from cota.actions.user_utter import UserUtter
        from cota.actions.bot_utter import BotUtter
        from cota.actions.form import Form

        actions = []
        for action in self.actions:
            if action.name == 'Selector':
                # Only output the 'thought' in result if present (now at same level as text)
                for result in action.result:
                    thought = result.get('thought', '')
                    if thought:
                        actions.append('thought:' + thought)
            else:
                for result in action.result:
                    if len(result.get('text', '')) > 0:
                        # Check if action has slots and display them
                        if isinstance(action, Form) and hasattr(action, 'slots') and action.slots:
                            slot_json = json.dumps(action.slots, ensure_ascii=False)
                            actions.append(f"{action.name}({slot_json}):{result.get('text','')}")
                        else:
                            actions.append(action.name + ':' + result.get('text',''))
        return '\n'.join(actions)


    def task_description(self, action:Action = None):
        return self.agent.description
    
    def agent_description(self, action:Action = None):
        return self.agent.description

    def current_form_name(self, action:Action = None):
        from cota.actions.form import Form
        if isinstance(action, Form):
            return action.name
        if isinstance(self.latest_action, Form):
            return self.latest_action.name
        if self.current_form:
            return self.current_form.name
        return ""

    def current_form_description(self, action:Action = None):
        from cota.actions.form import Form
        if isinstance(action, Form):
            return action.description
        if isinstance(self.latest_action, Form):
            return self.latest_action.description
        return ""

    def current_form_execute_result(self, action:Action=None):
        from cota.actions.form import Form
        if isinstance(action, Form):
            return '\n'.join([result.get("text", "") for result in action.result])
        if isinstance(self.latest_action, Form):
            return '\n'.join([result.get("text", "") for result in self.latest_action.result])
        return ""

    def current_form_slot_names(self, action:Action = None):
        from cota.actions.form import Form
        if isinstance(action,Form):
            action_config = self.agent.actions.get(action.name, {})
            slots =  action_config.get("slots", {})
            return ','.join([slot for slot in slots])
        if isinstance(self.latest_action, Form):
            action_config = self.agent.actions.get(self.latest_action.name, {})
            slots =  action_config.get("slots", {})
            return ','.join([slot for slot in slots])
        return ""

    def current_form_slot_descriptions(self, action:Action = None):
        from cota.actions.form import Form
        if isinstance(action, Form):
            action_config = self.agent.actions.get(action.name, {})
            slots =  action_config.get("slots", {})
            return '\n'.join(['{}:{}'.format(key,value.get("description","")) for key,value in slots.items()])
        if isinstance(self.latest_action, Form):
            action_config = self.agent.actions.get(self.latest_action.name, {})
            slots =  action_config.get("slots", {})
            return '\n'.join(['{}:{}'.format(key,value.get("description","")) for key,value in slots.items()])
        return ""

    def current_form_slot_states(self, action:Action = None):
        from cota.actions.form import Form
        if isinstance(action, Form) and action.slots:
            return json.dumps(action.slots, ensure_ascii=False, indent=4)
        if isinstance(self.latest_action, Form) and self.latest_action.slots:
            return json.dumps(self.latest_action.slots, ensure_ascii=False, indent=4)
        if self.current_form:
            return json.dumps(self.current_form.slots, ensure_ascii=False, indent=4)
        return '{}'

    def current_form_messages(self, action:Action = None):
        from cota.actions.user_utter import UserUtter
        from cota.actions.bot_utter import BotUtter
        from cota.actions.form import Form

        # Get current form name
        current_form = action if isinstance(action, Form) else self.latest_action
        if not isinstance(current_form, Form):
            return ""
        current_form_name = current_form.name

        index = -1
        if action.name == current_form_name and action.state == "start":
            index = len(self.actions) - 1

        for i, action in enumerate(reversed(self.actions)):
            if index > 0:
                if action.name == 'Query':
                    index = len(self.actions) - 1 - i
                    break
                else:
                    index = len(self.actions) - i
                    break

            if action.name == current_form_name and action.state == "start":
                index = len(self.actions) - 1 - i
                if index == 0:
                    break

        if index != -1:
            form_actions = list(self.actions)[index:]
            messages = []
            for action in form_actions:
                if isinstance(action, UserUtter):
                    for message in action.result:
                        messages.append(f"user: {message.get('text', '')}")
                if isinstance(action, BotUtter):
                    for message in action.result:
                        messages.append(f"assistant: {message.get('text', '')}")

        return '\n'.join(messages)

    def thoughts(self, action: Action = None):
        return self.agent.dpl.generate_thought(self, action)
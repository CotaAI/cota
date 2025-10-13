import os
import logging
import itertools
from pathlib import Path
from typing import Text, List, Union, Optional, Dict, Any
from cota.dst import DST
from cota.actions.action import Action
from cota.dpl.dpl import DPL

from cota.utils.io import read_yaml_from_path

from cota.utils.common import (
    hash_str
)

logger = logging.getLogger(__name__)

class TriggerDPL(DPL):
    def __init__(
            self,
            path: Union[Text, Path],
            actions_config: Dict[Text, Any]
    ) -> None:
        self.actions_config = actions_config
        self.features = self.build(path)

    def build(self, path: Union[Text, Path]) -> Dict[Text, List[Text]]:
        # Load policy data from path and process it into features
        policies = self.load_data(path)
        return self.process_policies(policies)

    async def generate_actions(self, dst: DST) -> List[Text]:
        """Generate next action based on action history."""
        actions = dst.formless_actions
        if not actions:
            return None
        query_index = [i for i, a in enumerate(actions) if a.name == 'UserUtter']
        
        if not query_index:
            return None
        
        action_dicts = [action.as_dict() for action in actions]
        for q_index in query_index:
            segment = action_dicts[q_index:]
            
            keys = self._build_action_key(segment)
            for key in keys:
                matched_actions = self.features.get(key)
                if matched_actions:
                    return matched_actions
        return None

    def load_data(self, path: Union[Text, Path]) -> List[Dict]:
        """Load trigger policy data from YAML files.
        Only processes 'triggers' sections, ignoring other policy types.
        """
        policies = []
        path_obj = Path(path)

        if not path_obj.is_dir():
            logger.warning(f"Path {path} is not a directory")
            return policies

        # Process all YAML files in directory
        for yml_file in path_obj.glob('*.yml'):
            try:
                data = read_yaml_from_path(yml_file)
                
                # Only extract data from 'triggers' sections
                if isinstance(data, dict) and 'triggers' in data:
                    policies.extend(data['triggers'])
            except Exception as e:
                logger.error(f"Failed to load {yml_file}: {e}")
                
        return policies

    def process_policies(self, policies: List[Dict]) -> Dict[Text, List[Text]]:
        """Process policies to build features for action prediction.
        
        Args:
            policies: List of policy dictionaries containing action sequences
            
        Returns:
            Dictionary mapping action sequence keys t o predicted next actions
        """
        features = {}
        
        for policy in policies:
            actions = policy.get("actions", [])
            user_utter_indices = self.build_user_utter_index(actions)
            
            # Process each action sequence
            for i, action in enumerate(actions):
                segments = self.trace_back_to_user_utter(actions, i, user_utter_indices)
                
                for segment in segments:
                    if len(segment) < 2:
                        continue
                        
                    # Build key from action sequence excluding last action
                    keys = self._build_action_key(segment[:-1])
                    
                    # Store last action as prediction
                    predicted_action = segment[-1].get('name')
                    for key in keys:
                        features[key] = [predicted_action]
        return features

    def build_user_utter_index(self, actions: List[Dict]) -> List[int]:
        return [i for i, action in enumerate(actions) if action.get('name') == 'UserUtter']

    def trace_back_to_user_utter(self, actions: List[Dict], index: int, user_utter_index: List[int]) -> List[List[Dict]]:
        """Trace back from current action to previous UserUtter actions to build action segments."""
        segments = []
        for q_index in reversed(user_utter_index):
            if q_index < index:
                segment = [action for action in actions[q_index:index] 
                          if action.get('name') and action.get('name') not in ('Selector','Updater')]
                segment.append(actions[index])
                if len(segment) > 1:
                    segments.append(segment)
        return segments

    def _build_action_key(self, actions: List[Dict]) -> List[Text]:
        """Build key from action sequence for feature lookup."""
        form_configs = {
            name: config['executer']['output'] 
            for name, config in self.actions_config.items() 
            if 'executer' in config
        }

        def _is_form_action(action_name: Text) -> bool:
            return action_name in form_configs

        name_list = []
        for act in actions:
            action_name = act.get('name')
            if not action_name:
                continue
                
            result = act.get('result', [])
            
            if action_name == 'UserUtter':
                keys = self._generate_user_utter_keys(action_name, result)
            elif action_name in form_configs:    
                keys = self._generate_form_keys(action_name, result, form_configs[action_name])
            else:
                keys = [action_name]
            
            # Only add non-empty keys to avoid empty combinations
            if keys:
                name_list.append(keys)
        # Cross combine each element in name_list where each element is a list
        return ['_'.join(item) for item in itertools.product(*name_list)]

    def _generate_user_utter_keys(self, action_name: Text, result: List) -> List[Text]:
        """Generate keys for UserUtter actions."""
        keys = []
        for output in result:
            value = output if isinstance(output, str) else output.get('text', '')
            if value and value.strip():  # Check for non-empty meaningful text
                keys.append(f"{action_name}:{value}")
        return keys

    def _generate_form_keys(self, action_name: Text, result: List, allowed_outputs: List) -> List[Text]:
        """Generate keys for form actions with enumerated outputs."""
        for output in result:
            if isinstance(output, dict):
                value = output.get('text', '')
                if value and len(value) > 1:
                    if value in allowed_outputs:
                        return [f"{action_name}:{value}"]
                    else:
                        return [f"{action_name}:<text>"]
        return []
import os
import logging
from pathlib import Path
from typing import Text, List, Union, Optional, Dict
from cota.dst import DST
from cota.actions.action import Action
from cota.dpl.dpl import DPL

from cota.utils.io import read_yaml_from_path

from cota.utils.common import (
    hash_str
)

logger = logging.getLogger(__name__)

class MatchDPL(DPL):
    def __init__(
            self,
            path,
    ) -> None:
        self.features = self.build(path)

    def build(self, path: Union[Text, Path]) -> Dict[Text, List]:
        # Load policy data from path and process it into features
        policies = self.load_data(path)
        return self.process_policies(policies)

    def process_policies(self, policies: List[Dict]) -> Dict[Text, List]:
        """Process policies to build features for thought generation.
        
        Args:
            policies: List of policy dictionaries containing action sequences
            
        Returns:
            Dictionary mapping action sequence keys to thought segments
        """
        features = {}
        hash_keys = set()
        
        for policy in policies:
            actions = policy.get("actions")
            title = policy.get("title", "")
            if not actions:
                continue
            user_utter_index = self.build_user_utter_index(actions)
            
            for i, action in enumerate(actions):
                if 'thought' in action:
                    segments = self.trace_back_to_user_utter(actions, i, user_utter_index)
                    
                    for segment in segments:
                        key = '_'.join([action.get('name') for action in segment])
                        hash_key = '_'.join(f"{action.get('name')}:{action.get('thought', '')}" for action in segment)

                        if hash_str(hash_key) not in hash_keys:
                            hash_keys.add(hash_str(hash_key))
                            segment_with_title = {
                                'title': title,
                                'actions': segment
                            }
                            features.setdefault(key, []).append(segment_with_title)
        return features

    async def generate_thoughts(self, dst: DST, action: Action) -> Text:
        actions = dst.formless_actions
        segments = []
        query_index = [i for i, a in enumerate(actions) if a.name == 'UserUtter']
        for q_index in query_index:
            segment = []
            for i in range(q_index, len(actions)):
                segment.append(actions[i])
            if action:
                segment.append(action)
            segments.append(segment)

        thoughts = ""
        for segment in segments:
            key = '_'.join(action.name for action in segment)
            policies = self.features.get(key, [])
            for policy_data in policies:
                title = policy_data.get('title', '')
                features = policy_data.get('actions', [])
                
                if title:
                    thoughts = thoughts + "# {}\n".format(title)
                
                for feature in features:
                    if 'thought' in feature:
                        thoughts = thoughts + "thought:{}\n".format(feature.get('thought'))
                    if 'result' in feature:
                        thoughts = thoughts + "{}:{}\n".format(feature.get('name'), feature.get('result'))
                thoughts = thoughts + '\n'
            thoughts = thoughts + '\n'
        return thoughts

    def load_data(self, path: Union[Text, Path]) -> List[Dict]:
        """Load match policy data from YAML files.
        Only processes 'policies' sections, ignoring other policy types.
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
                
                # Only extract data from 'policies' sections
                if isinstance(data, dict) and 'policies' in data:
                    policies.extend(data['policies'])
            except Exception as e:
                logger.error(f"Failed to load {yml_file}: {e}")
                
        return policies

    def build_user_utter_index(self, actions):
        return [i for i, action in enumerate(actions) if action.get('name') == 'UserUtter']

    def trace_back_to_user_utter(self, actions, index, user_utter_index):
        segments = []
        for q_index in reversed(user_utter_index):
            if q_index < index:
                segment = [action for action in actions[q_index:index] if action.get('name') and action.get('name') not in ('Selector')]
                segment.append(actions[index])
                if len(segment) > 1:
                    segments.append(segment)
        return segments

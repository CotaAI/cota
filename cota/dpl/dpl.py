import os
import logging
from pathlib import Path
from typing import Text, List, Union, Optional, Dict, Any

logger = logging.getLogger(__name__)


class DPL:
    async def generate_thoughts(self, dst: 'DST', action: 'Action') -> Optional[Text]:
        """Generate thought for the next action. Return None if no thought is generated."""
        return None

    async def generate_actions(self, dst: 'DST') -> Optional[List[Text]]:
        """Generate next action names. Return None if no action is determined."""
        return None

class DPLFactory:
    @staticmethod
    def create(agent_config: Dict[Text, Any], path: Text) -> List['DPL']:
        """Create a list of DPL instances based on configuration.
        Multiple DPL instances can coexist based on policies configuration."""
        
        # Try to get policies from different configuration formats
        policies = []
        
        # New format: top-level "policies" (list)
        if "policies" in agent_config:
            policies = agent_config.get("policies", [])
                    
        if not policies:
            raise ValueError("No policies configured in configuration")
            
        dpl_list = []
        
        for policy in policies:
            policy_name = policy.get('name')
            
            if policy_name == 'trigger':
                from cota.dpl.trigger import TriggerDPL
                actions_config = agent_config.get("actions", {})
                dpl_list.append(TriggerDPL(
                    path=path,
                    actions_config=actions_config
                ))
                
            elif policy_name == 'match':
                from cota.dpl.match import MatchDPL
                dpl_list.append(MatchDPL(
                    path=path
                ))
                
            elif policy_name == 'rag':
                from cota.dpl.rag import RAGDPL
                dpl_list.append(RAGDPL(
                    path=path,
                    llm=policy.get('llm'),
                    max_thoughts=policy.get('max_thoughts', 5)
                ))
            else:
                raise ValueError(f"Unknown dialogue policy: {policy_name}")
            
        if not dpl_list:
            raise ValueError("No valid dialogue policy enabled in configuration")
            
        return dpl_list
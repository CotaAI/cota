import copy
import logging
from typing import Optional, List, Dict, Text, Any
from cota.channels.channel import Channel
from cota.actions.action import Action
from cota.actions.user_utter import UserUtter
from cota.actions.bot_utter import BotUtter
from cota.actions.form import Form
from cota.message.message import Message
from cota.store import Store
from cota.dst import DST

logger = logging.getLogger(__name__)

class Processor:
    def __init__(
            self,
            agent: 'Agent',
            store: Store
    ):
        self.agent = agent
        self.store = store
        self.dst = None  # todo

    def _get_dst(self):
        pass

    def _update_dst(self):
        pass

    async def handle_message(
            self,
            message: Message,
            channel: Optional[Channel] = None
    ):
        """handle message"""
        if self.agent.dialogue.get('use_proxy_user') == True:
            await self._handle_message_proxy(message, channel)
            return

        action = Action.build_from_name(name='UserUtter')
        action.run_from_dict({
            "result": [message.as_dict()],
            "sender": message.sender or 'user',
            "sender_id": message.sender_id or 'default_user',
            "receiver": message.receiver or 'bot',
            "receiver_id": message.receiver_id or 'default_bot'
        })

        if channel:
            await self.execute_channel_effects(action, message.session_id, channel)

        self.dst = await self.get_tracker(message.session_id)
        self.dst.update(action)

        if message.receiver != 'bot':
            await self.save_tracker(self.dst)
            return

        await self._handle_bot_actions(message.session_id, channel)
        await self.save_tracker(self.dst)

    # TODO: Check if this is reasonable
    async def handle_session(self, session_id:Text, channel: Optional[Channel] = None):
        self.dst = await self.get_tracker(session_id)
        await self._handle_bot_actions(session_id, channel)
        await self.save_tracker(self.dst)

    async def _handle_message_proxy(self, message: Message, channel: Optional[Channel] = None):
        self.dst = await self.get_tracker(message.session_id)
        # user = message.metadata.get('user') or self.agent.user

        max_proxy_step = self.agent.dialogue.get('max_proxy_step')                
        for i in range(max_proxy_step):
            action_config = self.agent.actions.get('UserUtter', {})
            action = Action.build_from_name(
                name='UserUtter',
                description=action_config.get("description", ''),
                prompt=action_config.get("prompt", '')
            )
            # await action.run(self.agent, self.dst, user=user)
            await action.run(self.agent, self.dst)
            self.dst.update(action)
            
            # Output user's message to channel first
            if channel:
                await self.execute_channel_effects(action, message.session_id, channel)
            
            # Check if user wants to stop the conversation based on state field in JSON response
            if action.result and action.result[0].get('state', 'continue') == 'stop':
                logger.debug(f"Conversation ending - Final DST state: \n {self.dst.current_state()}")
                return 

            await self._handle_bot_actions(message.session_id, channel)
        await self.save_tracker(self.dst)


    async def _handle_bot_actions(self, session_id: Text, channel: Optional[Channel] = None):
        while True:
            bot_actions = await self.agent.generate_actions(self.dst)
            for action_item in bot_actions:
                # All actions are single actions now (no tuple handling)
                await action_item.run(self.agent, self.dst)
                self.dst.update(action_item)
                logger.debug(f"After DST updated: \n {self.dst.current_state()}")
                if channel:
                    await self.execute_channel_effects(action_item, session_id, channel)
                if isinstance(action_item, BotUtter):
                    return
            if len(bot_actions) > 1 and isinstance(bot_actions[-1], Form) and isinstance(bot_actions[-2], BotUtter):
                break
    async def get_tracker(
            self, session_id: Text
    ) -> Optional[DST]:
        """Get tracker based on session_id"""
        actions_dict = await self.store.retrieve(session_id)
        if actions_dict is None:
            return DST(session_id=session_id, agent=self.agent)
        else:
            tracker = DST.from_dict(
                dst_dict={ "session_id": session_id, "actions": actions_dict}, 
                agent=self.agent
            )
            return tracker

    async def save_tracker(self, tracker: DST) -> None:
        """Save tracker to tracker store"""
        await self.store.save(tracker)

    async def execute_channel_effects(
            self,
            action: Action,
            session_id: Text,
            channel: Channel,
    ) -> None:
        if isinstance(action, UserUtter):
            for res in action.result:
                await channel.send_response(session_id, copy.deepcopy(res))
        elif isinstance(action, BotUtter):
            for res in action.result:
                await channel.send_response(session_id, copy.deepcopy(res))
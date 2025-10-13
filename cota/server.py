# encoding:utf-8
import os
import json
from pathlib import Path
from sanic import Sanic, response
from sanic.request import Request
from sanic.response import HTTPResponse
from sanic_cors import CORS

from cota.agent import Agent
from typing import Text, Any, Optional
from cota.message.message import Message
from cota.channels.utils import convert_utters_dict

def create_app(
        agent: Optional[Agent] = None,
) -> Sanic:
    app = Sanic("cota")
    # Allow cross-origin access
    app.config.CORS_AUTOMATIC_OPTIONS = True
    app.config.CORS_SUPPORTS_CREDENTIALS = True
    app.config.CORS_EXPOSE_HEADERS = "filename"
    CORS(
        app, resources={r"/*": {"origins": "*"}}, automatic_options=True
    )

    app.ctx.agent = agent

    @app.get("/version")
    async def get_version(request: Request) -> HTTPResponse:
        from cota import __version__
        return response.json(
            {
                "version": __version__
            }
        )

    @app.post("add/message/<session_id>/tracker")
    async def add_message(request: Request, session_id: Text) -> HTTPResponse:
        # todo valid request body
        request_params = request.json
        text = request_params.get("text")
        sender = request_params.get("sender")
        sender_id = request_params.get("sender_id")
        meta_data = request_params.get("meta_data")
        # Generate message
        message = Message(text=text, sender=sender, sender_id=sender_id, session_id=session_id, metadata=meta_data)
        # TODO: Need lock here
        processor = app.ctx.agent.create_processor()
        processor.handle_message(message)
        return response.json(processor.dst.current_state())

    @app.get("get/conversations/<conversation_id>/tracker")
    async def get_tracker(request: Request, conversation_id: Text):
        """Get tracker based on conversation_id"""
        processor = app.ctx.agent.create_processor()
        dst = processor.get_tracker(conversation_id)
        return  response.json(dst.current_state())

    @app.get("get/latest/utter/conversations")
    async def get_latest_utter_conversations(request: Request):
        """Get corresponding utters based on session_ids"""
        conversation_ids = json.loads(request.args.get("conversation_ids"))

        if not conversation_ids:
            return response.json({'conversations':[]})

        print("List to query in request: ", conversation_ids)
        store = app.ctx.agent.store
        latest_utters = await store.latest_utter(conversation_ids)
        result = []
        for utter in latest_utters:
            utter_dict_list = convert_utters_dict(utter.get('result',[]))
            if len(utter_dict_list) > 0:
                result.append(utter_dict_list[-1])

        print("server.py obtained latest_utters: ", result)
        return response.json({
            'conversations': result
        })

    @app.get("get/history/message/conversation/<conversation_id>")
    async def get_history_message_by_conversationid(request: Request, conversation_id: Text):
        """Get historical dialogue based on conversation_id"""
        if not conversation_id:
            return response.text("Conversation ID not provided", status=400)

        store = app.ctx.agent.store
        conversations = await store.retrieve(conversation_id) or []

        result = []
        for conversation in conversations:
            if conversation.get('name') in ['Query','Response']:
                action_result = convert_utters_dict(conversation.get('result', []))
                result.extend(action_result)

        return response.json({'conversations': result})

    return app

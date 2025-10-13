import json
from typing import Dict, List

def convert_message_dict(message:Dict) -> List[Dict]:
    """Convert message dict format to fixed output style"""
    metadata = message.get("metadata", None)
    if metadata:
         message.update(metadata)

    result=[]
    text = message.get("text")
    image = message.get("image")

    if text:
        result.append(
            {
                'type': 'text',
                'text': text,
                'sender': message.get("sender", None),
                'sender_id': message.get('sender_id', None),
                'receiver': message.get("receiver", None),
                'receiver_id': message.get("receiver_id", None),
                'session_id': message.get("session_id", None),
                'metadata': message.get("metadata", {})
            }
        )
    
    if image:
        result.append(
            {
                'type': 'image',
                'payload': {"src": image},
                'sender': message.get("sender", None),
                'sender_id': message.get('sender_id', None),
                'receiver': message.get("receiver", None),
                'receiver_id': message.get("receiver_id", None),
                'session_id': message.get("session_id", None),
                'metadata': message.get("metadata", {})
            }
        )
    return result

def convert_utters_dict(utters:List[Dict]) -> List[Dict]:
    """Convert action's utters dict format to fixed output style"""
    result = []
    for message in utters:
        result.extend(convert_message_dict(message))
    return result
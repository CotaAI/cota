from typing import Optional, Text, Dict, Any
import uuid
class Message:
    def __init__(
            self,
            sender: Optional[Text] = None,
            sender_id: Optional[Text] = None,
            receiver: Optional[Text] = None,
            receiver_id: Optional[Text] = None,
            session_id: Optional[Text] = None,
            text: Optional[Text] = None,
            metadata: Optional[Dict] = None,
    ) -> None:

        if sender is not None:
            self.sender = str(sender)
        else:
            self.sender = 'user'

        if sender_id is not None:
            self.sender_id = str(sender_id)
        else:
            self.sender_id = 'default_user' if self.sender == 'user' else 'default_bot'

        if receiver is not None :
            self.receiver = str(receiver)

            if receiver_id is not None:
                self.receiver_id = str(receiver_id)
            else:
                self.receiver_id = 'default_bot' if self.receiver == 'bot' else 'default_user'
        else:
            self.receiver = None
            self.receiver_id = None

        if session_id is not None:
            self.session_id = str(session_id)
        else:
            self.session_id = uuid.uuid4().hex

        self.text = text.strip() if text else text
        self.metadata = metadata

    def as_dict(self) -> Dict[Text, Any]:
        return {
            'sender': self.sender,
            'sender_id': self.sender_id,
            'receiver': self.receiver,
            'receiver_id': self.receiver_id,
            'session_id': self.session_id,
            'text': self.text,
            'metadata': self.metadata
        }

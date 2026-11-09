"""Official SDK process entry point. JSON lines on stdio, no Cota runtime here."""
import contextlib
import json
import select
import sys
import time


class EventRelay:
    def __init__(self, source, destination):
        self.source, self.destination = source, destination
        self.sequence = 0

    def emit(self, frame):
        self.destination.write(json.dumps(frame, ensure_ascii=False) + '\n')
        self.destination.flush()

    def handle(self, event):
        import lark_oapi as lark
        self.sequence += 1
        identity = str(self.sequence)
        self.emit({'type': 'event', 'id': identity, 'event': json.loads(lark.JSON.marshal(event))})
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if not select.select([self.source], [], [], max(0, deadline - time.monotonic()))[0]:
                break
            raw = self.source.readline()
            if not raw:
                raise RuntimeError('Cota input stream closed')
            ack = json.loads(raw)
            if ack.get('id') != identity:
                continue  # discard a late acknowledgment for a timed-out event
            if not ack.get('accepted'):
                raise RuntimeError('Cota input queue unavailable')
            return
        raise TimeoutError('Cota input admission timed out')


def main():
    relay = EventRelay(sys.stdin, sys.stdout)
    try:
        config = json.loads(sys.stdin.readline())
        # The SDK's logging handler is created at import time using sys.stdout.
        # Keep diagnostics off our JSON protocol, and disable them below because
        # SDK connection errors can include signed URLs.
        with contextlib.redirect_stdout(sys.stderr):
            import lark_oapi as lark
            from lark_oapi.core.log import logger
            logger.disabled = True
            dispatcher = lark.EventDispatcherHandler.builder('', '').register_p2_im_message_receive_v1(relay.handle).build()
            class ConnectedClient(lark.ws.Client):
                # Small readiness adapter for the pinned SDK. Protocol, heartbeat,
                # reconnect and dispatch remain entirely in the official client.
                async def _connect(self):
                    await super()._connect()
                    relay.emit({'type': 'ready'})
            client = ConnectedClient(config['app_id'], config['app_secret'], event_handler=dispatcher)
            client.on_reconnecting = lambda: relay.emit({'type': 'reconnecting'})
            client.start()
    except Exception as error:
        relay.emit({'type': 'error', 'error_type': type(error).__name__})
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

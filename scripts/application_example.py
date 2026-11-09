"""Submit one trusted input through Application; no public HTTP server.

Run from an installed/editable Cota environment:
python scripts/application_example.py --config ./bots/weather --text '你好'
"""
import argparse
import asyncio
import json

from cota import Agent, Application


async def submit(args):
    agent = Agent.load_from_path(args.config)
    async with Application(agent) as application:
        submission = await application.submit(
            user_id=args.user_id, session_id=args.session_id,
            message_id=args.message_id, text=args.text)
        result = await submission.wait()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result['receipt']['status'] in ('failed', 'interrupted') else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Bot directory with configured endpoints.yml')
    parser.add_argument('--user-id', default='example:user1')
    parser.add_argument('--session-id', default='example:conversation1')
    parser.add_argument('--message-id', help='Reuse the same ID when retrying an input')
    parser.add_argument('--text', required=True)
    return asyncio.run(submit(parser.parse_args()))


if __name__ == '__main__':
    raise SystemExit(main())

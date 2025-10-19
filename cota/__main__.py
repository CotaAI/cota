# encoding:utf-8
import argparse
import os
import shutil
import sys
import logging
import ssl
from typing import Text, Optional, Dict, Any
from sanic import Sanic
import asyncio
from cota import server
from cota.task import Task
from cota.agent import Agent
from cota.channels import channel, socketio, websocket, cmdline, sse
from cota.utils.common import list_routes
from cota import __version__

logger = logging.getLogger(__name__)

def validate_ssl_files(cert_path: str, key_path: str) -> bool:
    """Validate SSL certificate and key files"""
    try:
        if not os.path.exists(cert_path):
            raise FileNotFoundError(f"SSL certificate file not found: {cert_path}")
        if not os.path.exists(key_path):
            raise FileNotFoundError(f"SSL key file not found: {key_path}")
            
        context = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(cert_path, keyfile=key_path)
        return True
    except (FileNotFoundError, ssl.SSLError) as e:
        raise ValueError(f"Invalid SSL configuration: {str(e)}")

def create_server_config(args):
    """Create server configuration including SSL settings"""
    server_config = {
        'host': args.host,
        'port': args.port,
        'debug': args.debug
    }
    
    if args.ssl_cert and args.ssl_key:
        # Validate SSL files before creating config
        if validate_ssl_files(args.ssl_cert, args.ssl_key):
            server_config['ssl'] = {
                'cert': args.ssl_cert,
                'key': args.ssl_key
            }
    
    return server_config

def run(args):
    agent = Agent.load_from_path(path=args.config)
    app = server.create_app(agent)

    # Define channel configurations
    channel_configs = {
        'socket.io': {
            'class': socketio.SocketIO,
            'kwargs': {},
            'register_kwargs': {'route': '/webhooks/'}
        },
        'websocket': {
            'class': websocket.Websocket,
            'kwargs': {
                'connection_timeout': 1000,
                'room_timeout': 3600
            },
            'register_kwargs': {}
        },
        'sse': {
            'class': sse.SSE,
            'kwargs': {
                'connection_timeout': 1000,
                'room_timeout': 3600
            },
            'register_kwargs': {}
        }
    }

    # Initialize and register channel
    if args.channel not in channel_configs:
        raise ValueError(f"Unsupported channel: {args.channel}. "
                        f"Available channels: {list(channel_configs.keys())}")
    
    config = channel_configs[args.channel]
    channel_class = config['class']
    
    try:
        input_channels = channel_class(**config['kwargs'])
        channel.register([input_channels], app, **config['register_kwargs'])
        
        # Configure logging for the channel
        logger = logging.getLogger(f"cota.channels.{args.channel}")
        logger.info(f"Initialized {args.channel} channel")
        
        list_routes(app)
        
        # Run server with configuration
        server_config = create_server_config(args)
        app.run(**server_config)
        
    except Exception as e:
        logger.error(f"Failed to initialize {args.channel} channel: {e}")
        raise


async def shell(args):
    agent = Agent.load_from_path(path=args.config)
    print("Agent loaded. Type a message and press enter.")

    async def handler(message, channel):
        await agent.processor.handle_message(message, channel)
    
    cmdline_channel = cmdline.Cmdline(on_new_message=handler)
    await cmdline_channel.on_connect()

async def task(args):
    """Task功能暂未完成，将在下个版本中提供"""
    print("🚧 Task功能正在开发中，将在下个版本提供！")
    print("📋 当前可用功能:")
    print("   • cota run    - 启动对话代理")
    print("   • cota shell  - 启动交互式命令行")
    print("   • cota init   - 初始化项目")
    print("   • cota server - 启动API服务器")
    
    # TODO: 在下个版本中实现以下功能
    # task = Task.load_from_path(path=args.config)
    # print("Task loaded.")
    # await task.run()

def init(args):
    # Define the directory and files to be created
    project_dir = "cota_projects"
    template_dir = "bots"

    # Create the project directory
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
        print(f"Created directory: {project_dir}")
    else:
        print(f"Directory {project_dir} already exists.")

    src_dir = os.path.join(os.path.dirname(__file__), template_dir)
    src_dir = os.path.abspath(src_dir)
    
    if src_dir and os.path.exists(src_dir):
        for item in os.listdir(src_dir):
            if item.startswith('.'):
                continue
                
            src_item = os.path.join(src_dir, item)
            dst_item = os.path.join(project_dir, item)
            try:
                if os.path.isdir(src_item):
                    if os.path.exists(dst_item):
                        shutil.rmtree(dst_item)
                    shutil.copytree(src_item, dst_item)
                    print(f"Copied directory: {item}")
                else:
                    shutil.copy2(src_item, dst_item)
                    print(f"Copied file: {item}")
            except Exception as e:
                print(f"Error copying {item}: {str(e)}")
        print(f"Project template created in: {os.path.abspath(project_dir)}")
    else:
        print(f"Template directory not found at: {src_dir}")
        print("Creating empty project directory only.")

def configure_logging(log_level=logging.INFO):
    """Configure logging with the specified level"""
    # Set the root logger level
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Configure basic logging format
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Add console handler if not already present
    if not root_logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    else:
        # Update existing handlers' formatters
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)
    
    # Set level for all handlers
    for handler in root_logger.handlers:
        handler.setLevel(log_level)

def create_argument_parser() -> argparse.ArgumentParser:
    """ """
    # create the top-level parser
    parser = argparse.ArgumentParser(
            prog="cota",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            description="cota command line interface."
    )

    parser.add_argument(
            "--version",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Print installed cota version"
    )

    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parsers = [parent_parser]

    subparsers = parser.add_subparsers(help="cota commands")

    # create the parser for the "run" command
    parser_run = subparsers.add_parser(
            "run",
            parents=parent_parsers,
            conflict_handler="resolve",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            help="Starts a cota server."
    )

    parser_run.add_argument('--host', default='0.0.0.0', type=str, help="Host to run the service")
    parser_run.add_argument('--port', default=5005, type=int, help="Port to run the service")
    parser_run.add_argument('--config', default='./', type=str, help="agent config")
    parser_run.add_argument('--channel', default='socket.io', type=str, help="Message channel")
    parser_run.add_argument('--debug', action='store_true', help="Enable debug mode (sets log level to DEBUG)")
    parser_run.add_argument('--log', default='INFO', type=str, help="Set the logging level")
    parser_run.add_argument('--ssl-cert', type=str, help="SSL certificate file path")
    parser_run.add_argument('--ssl-key', type=str, help="SSL private key file path")
    def run_with_debug(args):
        if args.debug:
            args.log = 'DEBUG'
        configure_logging(getattr(logging, args.log.upper(), logging.INFO))
        run(args)
    parser_run.set_defaults(func=run_with_debug)

    # create the parser for the "shell" command
    parser_shell = subparsers.add_parser(
        "shell",
        parents=parent_parsers,
        conflict_handler="resolve",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        help="Interacting with cota by commandline."
    )

    parser_shell.add_argument('--config', default='./', type=str, help="agent config path")
    parser_shell.add_argument('--log', default='INFO', type=str, help="Set the logging level")
    parser_shell.add_argument('--debug', action='store_true', help="Enable debug mode (sets log level to DEBUG)")
    
    def run_shell(args):
        if args.debug:
            args.log = 'DEBUG'
        configure_logging(getattr(logging, args.log.upper(), logging.INFO))
        return asyncio.run(shell(args))
    
    parser_shell.set_defaults(func=run_shell)

    # create the parser for the "task" command
    parser_task = subparsers.add_parser(
        "task",
        parents=parent_parsers,
        conflict_handler="resolve",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        help="Executing cota in task mode."
    )

    parser_task.add_argument('--config', default='./', type=str, help="task config path")
    parser_task.add_argument('--log', default='INFO', type=str, help="Set the logging level")
    parser_task.add_argument('--debug', action='store_true', help="Enable debug mode (sets log level to DEBUG)")
    
    def run_task(args):
        if args.debug:
            args.log = 'DEBUG'
        configure_logging(getattr(logging, args.log.upper(), logging.INFO))
        return asyncio.run(task(args))
    
    parser_task.set_defaults(func=run_task)

    # create the parser for the "init" command
    parser_init = subparsers.add_parser(
        "init",
        parents=parent_parsers,
        conflict_handler="resolve",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        help="Initialize a new cota project."
    )
    parser_init.add_argument('--log', default='INFO', type=str, help="Set the logging level")
    parser_init.set_defaults(func=init)

    return parser

def main():
    parser = create_argument_parser()
    cmdline_arguments = parser.parse_args()

    if hasattr(cmdline_arguments, "func"):
        log_level = getattr(logging, cmdline_arguments.log.upper())
        configure_logging(log_level)
        cmdline_arguments.func(cmdline_arguments)
    elif hasattr(cmdline_arguments, "version"):
        print(f"Cota version: {__version__}")


if __name__ == "__main__":
    main()

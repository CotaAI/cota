# encoding:utf-8
import argparse
import os
import shutil
import sys
import logging
import re
import ssl
from typing import Dict, Any
import asyncio
from cota import server
from cota.agent import Agent
from cota.channels import cmdline
from cota.channels.queue import MessageBus
from cota.utils.common import list_routes
from cota import __version__
from cota.templates import bot_templates_dir, TEMPLATE_IGNORE

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
        'debug': args.debug,
        'single_process': True  # Use single process mode to avoid worker issues
    }
    
    if bool(args.ssl_cert) != bool(args.ssl_key):
        raise ValueError('SSL certificate and key must be provided together')
    if args.ssl_cert and args.ssl_key:
        # Validate SSL files before creating config
        if validate_ssl_files(args.ssl_cert, args.ssl_key):
            server_config['ssl'] = {
                'cert': args.ssl_cert,
                'key': args.ssl_key
            }
    
    return server_config

def _register_tunnel_listener(app, port: int, tunnel_type: str = "localhostrun"):
    """Register Sanic listeners to start/stop a tunnel.

    Supported tunnel types:
    - localhostrun: SSH-based tunnel (no login required)
    - cloudflared: Cloudflare tunnel (requires cloudflared installed)
    - ngrok: ngrok tunnel (requires ngrok installed)
    """
    tunnel_type = tunnel_type.lower()

    async def start_localhostrun():
        """Start localhost.run SSH tunnel."""
        logger.info("Starting localhost.run tunnel...")
        proc = await asyncio.create_subprocess_exec(
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ServerAliveInterval=30",
            "-R", f"80:localhost:{port}",
            "nokey@localhost.run",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        return proc, r"https://[a-zA-Z0-9\-]+\.lhr\.life"

    async def start_cloudflared():
        """Start Cloudflare tunnel."""
        logger.info("Starting cloudflared tunnel...")
        proc = await asyncio.create_subprocess_exec(
            "cloudflared",
            "tunnel",
            "--url", f"http://localhost:{port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        return proc, r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com"

    async def start_ngrok():
        """Start ngrok tunnel."""
        logger.info("Starting ngrok tunnel...")
        proc = await asyncio.create_subprocess_exec(
            "ngrok",
            "http",
            str(port),
            "--log=stdout",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        return proc, r"https://[a-zA-Z0-9\-]+\.ngrok(-free)?\.app"

    # Select tunnel startup function
    tunnel_funcs = {
        "localhostrun": start_localhostrun,
        "cloudflared": start_cloudflared,
        "ngrok": start_ngrok,
    }

    if tunnel_type not in tunnel_funcs:
        logger.warning(f"Unknown tunnel type: {tunnel_type}, using localhost.run")
        tunnel_type = "localhostrun"

    start_func = tunnel_funcs[tunnel_type]

    @app.listener("after_server_start")
    async def start_tunnel(app, loop):
        try:
            proc, url_pattern = await start_func()
            app.ctx.tunnel_process = proc

            async def watch_output():
                pattern = re.compile(url_pattern)
                async for line in proc.stdout:
                    text = line.decode(errors='replace').strip()
                    if text:
                        match = pattern.search(text)
                        if match and not getattr(app.ctx, 'tunnel_url', None):
                            url = match.group(0)
                            print("\n" + "=" * 50)
                            print("  🎉  公网访问地址:")
                            print(f"  🔗  {url}")
                            print("  📱  启用 --chat-app 后可打开 /chat/ 聊天")
                            print("=" * 50 + "\n")
                            # Store tunnel URL for API access
                            app.ctx.tunnel_url = url

            app.ctx.tunnel_watcher = asyncio.create_task(watch_output())
        except FileNotFoundError:
            logger.error(f"Tunnel command not found. Please install {tunnel_type}")
            logger.error("  - localhost.run: SSH (usually pre-installed)")
            logger.error("  - cloudflared: https://developers.cloudflare.com/cloudflare-one/infrastructure/tunnel/")
            logger.error("  - ngrok: https://ngrok.com/download")

    @app.listener("after_server_stop")
    async def stop_tunnel(app, loop):
        proc = getattr(app.ctx, "tunnel_process", None)
        try:
            if proc and proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    await proc.wait()
                logger.info("Tunnel stopped")
        finally:
            watcher = getattr(app.ctx, 'tunnel_watcher', None)
            if watcher:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)


def _load_channel_config(config_path: str) -> Dict[str, Any]:
    """Deployment settings override each channel's agent.yml defaults."""
    import yaml
    channels = {}
    for filename in ('agent.yml', 'endpoints.yml'):
        config_file = os.path.join(config_path, filename)
        if not os.path.exists(config_file):
            continue
        with open(config_file, encoding='utf-8') as stream:
            config = yaml.safe_load(stream) or {}
        if not isinstance(config, dict) or not isinstance(config.get('channels', {}), dict):
            raise ValueError(f'{filename}: channels must be a mapping')
        for name, settings in config.get('channels', {}).items():
            if not isinstance(name, str) or not isinstance(settings, dict):
                raise ValueError(f'{filename}: channels entries must be named mappings')
            channels[name] = {**channels.get(name, {}), **settings}
    return channels


def run(args):
    agent = Agent.load_from_path(path=args.config)
    configure_execution_logging(agent, args)
    factory = server.create_app
    if getattr(args, 'chat_app', False):
        from cota.webapp import create_app
        factory = create_app
    app = factory(agent, config_path=args.config,
                  channel_config=_load_channel_config(args.config))
    tunnel_type = getattr(args, 'tunnel', None)
    if tunnel_type:
        _register_tunnel_listener(app, args.port, tunnel_type)
    list_routes(app)
    app.run(**create_server_config(args))


async def _start_scheduler(agent: Agent, config_path: str, *, message_bus):
    """Schedule shell inputs through its serial queue, preserving conversation identity."""
    from cota.executor.scheduler import SchedulerService, set_scheduler_service
    from cota.channels.events import InboundMessage

    service = SchedulerService(store_path=os.path.join(config_path, 'scheduler_jobs.json'),
                               config_path=config_path)

    async def on_job_fire(job):
        text = job.payload.get('text', f'[Reminder] {job.name}')
        await message_bus.publish_inbound(InboundMessage(
            channel='scheduler', sender_id=job.user_id or 'scheduler',
            chat_id=job.session_id or 'default', session_key_override=job.session_id or None,
            content=f'[定时提醒] {text}', metadata={'source': 'scheduler', 'job_name': job.name}))

    service.set_callback(on_job_fire)
    set_scheduler_service(service)
    await service.start()
    return service


async def shell(args):
    """Start single-agent interactive shell."""
    config_path = args.config

    agent = Agent.load_from_path(path=config_path)
    if (getattr(agent, 'dialogue', None) or {}).get('mode', 'direct') != 'direct':
        await agent.cleanup()
        raise ValueError('cota shell requires dialogue.mode=direct; use Application or a group Channel for group mode')
    configure_execution_logging(agent, args)

    # ── Single agent shell ──
    sys.stderr.write("Agent loaded. Type a message and press enter.\n")
    sys.stderr.flush()

    # Create message bus and cmdline channel
    message_bus = MessageBus()

    is_debug = getattr(args, "debug", False)

    # Create cmdline channel
    cmdline_channel = cmdline.Cmdline(
        config={},
        bus=message_bus,
        debug=is_debug,
    )

    # Local observation only: no Runtime hooks or extra persistence path.
    latest_processor = None
    debug_viewer = None
    if is_debug:
        from cota.debug.inspector import Inspector
        from cota.debug.server import DebugServer
        inspector = Inspector(agent, cmdline_channel.session_key,
                              lambda: getattr(latest_processor, 'dst', None))
        debug_viewer = DebugServer(inspector)
        try:
            url = await debug_viewer.start()
            sys.stderr.write(f'Debug 页面：{url}\n')
            sys.stderr.flush()
        except Exception as error:
            logger.warning('Debug 页面未启动（%s），Shell 继续运行', type(error).__name__)
            await debug_viewer.close()
            debug_viewer = None

    # Set up message handler for processing incoming messages
    async def handle_inbound(inbound_msg):
        nonlocal latest_processor
        processor = agent.create_processor(message_bus=message_bus)
        if is_debug and inbound_msg.session_key == cmdline_channel.session_key:
            latest_processor = processor
        try:
            await processor.handle_inbound_message(inbound_msg)
        except Exception as e:
            logger.error(f"Error processing message: {e}")
        finally:
            if is_debug:
                cmdline_channel.flush_output()

    # Start a task to consume inbound messages from message bus
    async def consume_inbound():
        while True:
            try:
                inbound_msg = await message_bus.consume_inbound()
                if inbound_msg:
                    await handle_inbound(inbound_msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error consuming inbound message: {e}")

    # Start a task to consume outbound messages and display via cmdline
    async def consume_outbound():
        while True:
            try:
                outbound_msg = await message_bus.consume_outbound(timeout=1.0)
                if outbound_msg is None:
                    break
                await cmdline_channel.send(outbound_msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error consuming outbound message: {e}")

    # Start scheduler service, passing the channel for output visibility
    scheduler_service = None
    consumers = []
    try:
        scheduler_service = await _start_scheduler(agent, config_path, message_bus=message_bus)
        await cmdline_channel.start()
        # Start message consumers
        consumers = [asyncio.create_task(consume_inbound()), asyncio.create_task(consume_outbound())]

        sys.stderr.write("Cmdline channel started. Type /stop to exit.\n")
        sys.stderr.flush()
        await cmdline_channel.wait_closed()
    finally:
        for task in consumers:
            task.cancel()
        await asyncio.gather(*consumers, return_exceptions=True)
        try:
            await cmdline_channel.stop()
            if scheduler_service:
                await scheduler_service.stop()
        finally:
            try:
                if debug_viewer:
                    await debug_viewer.close()
            finally:
                await agent.cleanup()

def init(args):
    # Define the directory and files to be created
    project_dir = "cota_projects"
    src_dir = bot_templates_dir()

    # Create the project directory
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
        print(f"Created directory: {project_dir}")
    else:
        print(f"Directory {project_dir} already exists.")

    catalog = os.path.join(src_dir, "README.md")
    target_catalog = os.path.join(project_dir, "README.md")
    if os.path.isfile(catalog) and not os.path.lexists(target_catalog):
        shutil.copy2(catalog, target_catalog)
    for item in sorted(os.listdir(src_dir)):
        if item.startswith('.'):
            continue

        src_item = os.path.join(src_dir, item)
        dst_item = os.path.join(project_dir, item)
        if not all(os.path.isfile(os.path.join(src_item, name))
                   for name in ("agent.yml", "endpoints.yml")):
            continue
        if os.path.lexists(dst_item):
            print(f"Skipped existing Bot: {item}")
            continue
        try:
            shutil.copytree(src_item, dst_item, ignore=TEMPLATE_IGNORE)
            print(f"Copied Bot: {item}")
        except Exception as e:
            print(f"Error copying {item}: {str(e)}")
    print(f"Project template created in: {os.path.abspath(project_dir)}")

def configure_execution_logging(agent, args):
    if getattr(args, 'debug', False):
        path = agent.store.enable_debug_log(os.path.join(agent.workspace_path, 'debug', 'execution.log'))
        sys.stderr.write(f'完整执行日志：{path}\n')
        sys.stderr.flush()


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
    # Provider request bodies belong in Debug diagnostics, not scattered HTTP logs.
    for name in ('openai', 'httpx', 'httpcore'):
        logging.getLogger(name).setLevel(logging.WARNING)

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
    parser_run.add_argument('--chat-app', action='store_true', help="Enable the optional chat application at /chat/ (requires Web channel)")
    parser_run.add_argument('--debug', action='store_true', help="Start a local read-only Debug page for service sessions, capture model diagnostics and write execution events to workspace/debug/execution.log")
    parser_run.add_argument('--log', default='INFO', type=str, help="Set the logging level")
    parser_run.add_argument('--ssl-cert', type=str, help="SSL certificate file path")
    parser_run.add_argument('--ssl-key', type=str, help="SSL private key file path")
    parser_run.add_argument(
        '--tunnel',
        nargs='?',
        const='localhostrun',
        default=None,
        choices=['localhostrun', 'cloudflared', 'ngrok'],
        help="Expose bot via public tunnel. Options: localhostrun (default, SSH-based), cloudflared (Cloudflare), ngrok. Use --chat-app to enable the browser interface."
    )
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
    parser_shell.add_argument('--debug', action='store_true', help="Start a local read-only Debug page, capture model diagnostics in Store and write execution events")
    
    def run_shell(args):
        configure_logging(getattr(logging, args.log.upper(), logging.INFO))
        return asyncio.run(shell(args))
    
    parser_shell.set_defaults(func=run_shell)

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

    from cota.annotation_cli import add_annotation_parser
    add_annotation_parser(subparsers)
    from cota.policy.training import add_train_parser
    add_train_parser(subparsers)

    from cota.evaluation.cli import add_eval_parser
    add_eval_parser(subparsers)

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

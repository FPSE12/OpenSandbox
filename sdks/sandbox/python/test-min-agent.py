r"""Run mini-swe-agent in OpenSandbox, print its logs, then destroy the sandbox.

    uv run python test-min-agent.py -c config.json -m '你的任务'
    uv run python test-min-agent.py --image \
        26.21.10.10:30443/agent-eval/mini-swe-agent:user1-v1 \
        -c config.json -m '你的任务'

Use the tag published by mini-swe-agent/docs/opensandbox/push.sh.
Image priority: --image, OPEN_SANDBOX_IMAGE, DEFAULT_IMAGE.
Kubernetes pulls from Harbor over HTTPS using agents-env/harbor-pull and
the node's trusted CA. The SDK connects to OpenSandbox over the existing
local HTTP port-forward; OPEN_SANDBOX_API_KEY is the server key, not a Harbor token.

The supplied JSON is uploaded unchanged to
/home/sparkshield/mini-swe-agent/config.json. The command runs from
/home/sparkshield. Session eval_001 logs are read from the sandbox and printed;
no local output directory or log archive is created.
"""

import argparse
import asyncio
import json
import os
import shlex
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.exceptions import SandboxApiException
from opensandbox.models.execd import RunCommandOpts

AGENT_HOME = "/home/sparkshield"
AGENT_DIR = f"{AGENT_HOME}/mini-swe-agent"
AGENT_BIN = f"{AGENT_DIR}/.venv/bin/mcp-agent"
AGENT_CONFIG = f"{AGENT_DIR}/config.json"
SESSION_KEY = "eval_001"
DEFAULT_IMAGE = "26.21.10.10:30443/agent-eval/mini-swe-agent:24.04-20260922"


def load_config(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    config = json.loads(content)
    if not isinstance(config, dict) or not isinstance(config.get("model"), dict):
        raise ValueError("config must be a JSON object containing a model object")
    return content


def agent_command(message: str, remote_dir: str) -> str:
    return shlex.join(
        [
            AGENT_BIN,
            f"--message={message}",
            "-c",
            AGENT_CONFIG,
            "-o",
            f"{remote_dir}/output",
            "--session-key",
            SESSION_KEY,
            "--json",
        ]
    )


async def run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    # 连接 OpenSandbox 服务。
    connection = ConnectionConfig(
        domain=os.getenv("OPEN_SANDBOX_DOMAIN", "127.0.0.1:18082"),
        protocol=os.getenv("OPEN_SANDBOX_PROTOCOL", "http"),
        api_key=os.getenv("OPEN_SANDBOX_API_KEY", "sparkshield-api-key"),
        use_server_proxy=os.getenv("OPEN_SANDBOX_USE_SERVER_PROXY", "true").lower()
        == "true",
        request_timeout=timedelta(seconds=args.timeout + 60),
    )

    run_id = uuid4().hex
    remote_dir = f"{AGENT_HOME}/.agent-runs/{run_id}"
    print(f"Image: {args.image}", flush=True)
    sandbox = await Sandbox.create(
        image=args.image,
        entrypoint=["/bin/sleep", "infinity"],
        timeout=timedelta(seconds=args.timeout + 6000),
        ready_timeout=timedelta(seconds=180),
        connection_config=connection,
        metadata={"owner": "mini-agent-smoke"},
        env={"ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"]},
        resource={"cpu": "2", "memory": "4Gi"},
    )
    print(f"Sandbox: {sandbox.id}", flush=True)
    try:
        # 创建 Agent 输出目录。
        setup = await sandbox.commands.run(
            'test "$(id -u)" = 10001 && '
            f"mkdir -p {shlex.quote(remote_dir + '/output')}",
        )
        if setup.error or setup.exit_code != 0:
            raise RuntimeError(f"Cannot prepare sparkshield workspace: {setup}")
        try:
            # 上传用户配置。
            await sandbox.files.write_file(
                AGENT_CONFIG,
                config,
                mode=600,
                owner="sparkshield",
                group="sparkshield",
            )

            # 以 sparkshield 用户执行 Agent。
            execution = await sandbox.commands.run(
                agent_command(args.message, remote_dir),
                opts=RunCommandOpts(
                    working_directory=AGENT_HOME,
                    timeout=timedelta(seconds=args.timeout),
                ),
            )
            print("-------------------------------------------------")
            print(f"Agent command output: {execution.logs.stdout}", flush=True)
        finally:
            log_path = f"{remote_dir}/output/sessions/{SESSION_KEY}/events.jsonl"
            try:
                print("-------------------------------------------------")

                print(await sandbox.files.read_file(log_path), flush=True)
            except SandboxApiException as error:
                if error.status_code != 404:
                    raise
                print("Agent 未生成 events.jsonl，请查看上方命令输出。", flush=True)
        if execution.error or execution.exit_code != 0:
            raise RuntimeError(f"Agent command failed: {execution}")

    finally:
        await sandbox.destroy()
        print("-------------------------------------------------")

        print(f"Destroyed sandbox: {sandbox.id}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-m", "--message", required=True, help="Task text passed to mcp-agent"
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        required=True,
        help="Required local config.json to upload to the agent project directory",
    )
    parser.add_argument(
        "--timeout", type=int, default=600, help="Agent command timeout in seconds"
    )
    parser.add_argument(
        "--image",
        default=os.getenv("OPEN_SANDBOX_IMAGE", DEFAULT_IMAGE),
        help="Full Harbor image reference; defaults to OPEN_SANDBOX_IMAGE or "
        f"{DEFAULT_IMAGE}",
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


if __name__ == "__main__":
    asyncio.run(run(parse_args()))

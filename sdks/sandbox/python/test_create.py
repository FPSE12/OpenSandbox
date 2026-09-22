import asyncio
import os
from datetime import timedelta

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig


async def main() -> None:
    config = ConnectionConfig(
        domain=os.getenv("OPEN_SANDBOX_DOMAIN", "127.0.0.1:18082"),
        protocol=os.getenv("OPEN_SANDBOX_PROTOCOL", "http"),
        api_key=os.getenv("OPEN_SANDBOX_API_KEY", "sparkshield-api-key"),
        use_server_proxy=os.getenv("OPEN_SANDBOX_USE_SERVER_PROXY", "true").lower() == "true",
        request_timeout=timedelta(seconds=180),
    )

    sandbox = await Sandbox.create(
        # image="ubuntu-24.04-tools:latest",
        image=os.getenv(
            "OPEN_SANDBOX_IMAGE",
            "26.21.10.10:30500/agent-eval/ubuntu-tools:24.04-20260921",
        ),
        timeout=timedelta(minutes=30),
        connection_config=config,
        metadata={"owner": "workflow"},
        env={"OPEN_SANDBOX_TEST": "1"},
        resource={"cpu": "2", "memory": "4Gi"},
    )
    try:
        result = await sandbox.commands.run("python3 --version && node --version")
        print(result)
        await sandbox.files.write_file("/tmp/hello.txt", "hello sandbox\n")
        print(await sandbox.files.read_file("/tmp/hello.txt"))
    finally:
        await sandbox.destroy()


asyncio.run(main())

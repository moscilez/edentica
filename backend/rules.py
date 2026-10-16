"""Run pure JS validators without duplicating the educational rules during migration."""
import asyncio
import json
import os
from .database import ROOT


class Rules:
    async def call(self, operation, *args):
        process = await asyncio.create_subprocess_exec(
            os.getenv("NODE_PATH") or "node", str(ROOT / "scripts/program-rules.mjs"),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(
                (json.dumps({"operation": operation, "args": args}, ensure_ascii=False) + "\n").encode()), 15)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise RuntimeError("Не удалось выполнить проверку программы")
        result = json.loads(stdout)
        if "error" in result:
            raise ValueError(result["error"])
        return result["value"]

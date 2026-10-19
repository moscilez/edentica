import asyncio
import json
import os
import re
import sys
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import Response
from .database import ROOT


def pptx_available():
    # python-pptx is part of the portable runtime requirements.
    return True


async def subprocess_bytes(command, payload, timeout=60, maximum=20000000):
    process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,
                                                  stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                  cwd=ROOT)
    async def communicate():
        async def write():
            try:
                process.stdin.write(payload)
                await process.stdin.drain()
            finally:
                process.stdin.close()
        async def read():
            chunks, size = [], 0
            while chunk := await process.stdout.read(65536):
                size += len(chunk)
                if size > maximum:
                    raise ValueError("Слишком большой результат обработки")
                chunks.append(chunk)
            return b"".join(chunks)
        async def errors():
            while await process.stderr.read(65536):
                pass
        output, _, _ = await asyncio.gather(read(), write(), errors())
        await process.wait()
        if process.returncode:
            raise ValueError("Не удалось обработать документ. Проверьте формат и зависимости экспорта.")
        return output
    try:
        return await asyncio.wait_for(communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise


def gift(program):
    def escape(value):
        return re.sub(r"([\\~=#{}:])", r"\\\1", str(value)).replace("\r", " ").replace("\n", " ")
    questions = []
    for module in program.get("materials", {}).values():
        for q in module["questions"]:
            options = "\n".join(("=" if i == q["answer"] else "~") + escape(x) for i, x in enumerate(q["options"]))
            questions.append(f"// {', '.join(q['competencyIds'])}; тема {q['topicId']}\n::{escape(module['moduleId']+' '+q['id'])}::{escape(q['text'])} {{\n{options}\n#### {escape(q['explanation'])}\n}}")
    return "\n\n".join(questions).encode("utf-8")


async def export_program(program, format, module_id=None):
    payload = json.dumps(program, ensure_ascii=False).encode()
    if format=='report':
        from .reporting import report_html
        content,mime=report_html(program),'text/html; charset=utf-8'
    elif format=='zip':
        from io import BytesIO
        from zipfile import ZipFile,ZIP_DEFLATED
        from .docx_export import build
        from .slides import program_pptx
        from .reporting import report_html
        def archive():
            buffer=BytesIO()
            with ZipFile(buffer,'w',ZIP_DEFLATED) as z:
                z.writestr('program.docx',build(program));z.writestr('program.json',payload)
                z.writestr('tests.gift',gift(program));z.writestr('validation-report.html',report_html(program))
                for index,mid in enumerate(program['materials'],1):z.writestr(f'slides/module-{index}.pptx',program_pptx(program,mid))
            return buffer.getvalue()
        content,mime=await asyncio.to_thread(archive),'application/zip'
    elif format == "json":
        content, mime = payload, "application/json"
    elif format == "gift":
        content, mime = gift(program), "text/plain; charset=utf-8"
    elif format == "docx":
        from .docx_export import build
        content = await asyncio.to_thread(build,program)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif format == "pptx":
        from .slides import program_pptx
        content = await asyncio.to_thread(program_pptx,program,module_id)
        mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    else:
        raise HTTPException(422, "Неизвестный формат")
    return Response(content, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="edentica-draft-{program["id"]}.{"html" if format=="report" else format}"'})

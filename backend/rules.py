"""In-process Python validation and versioned skill instructions."""
import copy
import json
from .database import ROOT
from .validation import CONFIG,digest,inspect_skeleton,inspect_module,inspect_program


class Rules:
    async def call(self,operation,*args):
        operations={'digest':digest,'inspectSkeleton':inspect_skeleton,'inspectModule':inspect_module,'inspectProgram':inspect_program}
        if operation=='config':return copy.deepcopy(CONFIG)
        if operation=='demonstration':
            return json.loads((ROOT/'tests_python/fixtures/program.json').read_text(encoding='utf-8'))
        if operation not in operations:raise ValueError('Неизвестная операция проверки')
        result=operations[operation](*args)
        if operation=='inspectProgram':
            from .reporting import enrich
            return enrich(result,args[0])
        return result

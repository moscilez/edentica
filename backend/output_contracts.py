"""Provider-enforced output shapes; business invariants stay in Python checks."""
import copy
from .contracts import Intake,Outline,Competency,Lecture,LessonAssessment,Seminar,TestQuestion,Interview,FinalAssessment

def obj(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def array(items,minimum=0,maximum=150):return {'type':'array','items':items,'minItems':minimum,'maxItems':maximum}
def string():return {'type':'string','minLength':1}

def strict(schema):
    if isinstance(schema,list):return [strict(x) for x in schema]
    if not isinstance(schema,dict):return schema
    result={k:({name:strict(value) for name,value in v.items()} if k in ('properties','$defs') else strict(v))
        for k,v in schema.items() if k not in ('default','title')}
    if result.get('type')=='object':
        result['additionalProperties']=False
        if 'properties' in result:result['required']=list(result['properties'])
    return result

def shape(contract):return copy.deepcopy(contract.model_json_schema())

def schema_for(skill,payload):
    if skill in ('intake','intake_basic'):
        schema=shape(Intake);schema['properties'].pop('skeleton',None)
        # Numerical constraints are parsed by Python. Do not make a constrained
        # decoder emit dozens of irrelevant defaults for a short user brief.
        core={'type','totalHours','audience','entryLevel','format','assessment','title','requiredTopics'}
        fields=schema['$defs']['Requirements']['properties']
        schema['$defs']['Requirements']['properties']={k:v for k,v in fields.items() if k in core}
    elif skill=='outline':
        schema=shape(Outline)
        available=payload.get('availableStandards',[])
        if payload.get('requirements',{}).get('type')=='general':
            schema['$defs']['Competency']['properties']['standard']={'type':'null'}
        elif available:
            # The server owns legal titles, URLs and verification metadata.
            # Models select only existing identities and function codes.
            schema['$defs']['StandardLink']=obj({
                'code':{'type':'string','enum':[x['code'] for x in available]},
                'functionCode':{'type':'string','enum':list(dict.fromkeys(f for x in available for f in x['functions']))}})
    elif skill=='competency_repair':
        competency=shape(Competency);defs=competency.pop('$defs',{})
        competency['properties']['id']={'type':'string','enum':payload['missingIds']}
        competency['properties']['standard']={'type':'null'}
        schema=obj({'competencies':array(competency,len(payload['missingIds']),len(payload['missingIds']))})
        schema['$defs']=defs
    elif skill=='lesson':schema=shape(Lecture)
    elif skill=='assessment':schema=shape(LessonAssessment)
    elif skill in ('assignment','questions','interview'):
        key,contract={'assignment':('seminars',Seminar),'questions':('questions',TestQuestion),'interview':('interviews',Interview)}[skill]
        nested=shape(contract);defs=nested.pop('$defs',{})
        schema=obj({key:array(nested,1)});schema['$defs']=defs
    elif skill=='final_assessment':schema=shape(FinalAssessment)
    elif skill=='sections':
        final=shape(FinalAssessment);defs=final.pop('$defs',{})
        source=obj({'title':string(),'url':{'type':'string'},'kind':{'type':'string','enum':['documentation','literature','standard']},'reason':string()})
        schema=obj({'sections':obj({name:string() for name in payload['sectionTitles']}),'finalAssessment':final,'sources':array(source,0,30)})
        schema['$defs']=defs
    elif skill=='standards':
        schema=obj({'links':array(obj({'competencyId':{'type':'string','enum':[c['id'] for c in payload['competencies']]},
            'code':{'type':'string','enum':[s['code'] for s in payload['availableStandards']]},
            'functionCode':{'type':'string','enum':list(dict.fromkeys(f for s in payload['availableStandards'] for f in s['functions']))},'reason':string()}),0,40)})
    else:return None
    # Scope and cardinality are machine-readable instead of prose-only promises.
    topic=next(iter(payload.get('module',{}).get('topics',[])),None)
    if topic:
        def bind(node):
            if isinstance(node,dict):
                props=node.get('properties',{})
                if 'topicId' in props:props['topicId']={'type':'string','enum':[topic['id']]}
                if 'competencyIds' in props:props['competencyIds']=array({'type':'string','enum':topic['competencyIds']},1,len(topic['competencyIds']))
                for value in node.values():bind(value)
            elif isinstance(node,list):
                for value in node:bind(value)
        bind(schema)
    quota=payload.get('questionQuota')
    if skill in ('assessment','questions'):
        count=quota if quota is not None else 2
        schema['properties']['questions']['minItems']=count
        schema['properties']['questions']['maxItems']=count
    if skill in ('sections','final_assessment'):
        final=schema['properties']['finalAssessment'] if skill=='sections' else schema
        count=payload.get('requirements',{}).get('portfolioItems') or 0
        final['properties']['items']['minItems']=count;final['properties']['items']['maxItems']=count
    return strict(schema)

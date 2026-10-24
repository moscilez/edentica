"""Durable per-account model usage. No prompts, keys or response content are stored."""
from uuid import uuid4
from decimal import Decimal

PRICED_MODELS=('gigachat/gigachat-3-pro','gigachat-3-pro')
INPUT_RATE=Decimal('73.03')
OUTPUT_RATE=Decimal('176.39')

def cost(incoming,outgoing):
    a=Decimal(int(incoming))*INPUT_RATE/1_000_000
    b=Decimal(int(outgoing))*OUTPUT_RATE/1_000_000
    return {'inputRubles':float(a.quantize(Decimal('0.000001'))),'outputRubles':float(b.quantize(Decimal('0.000001'))),'totalRubles':float((a+b).quantize(Decimal('0.000001')))}



def tokens(value):
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else 0


def reply_metadata(data, model):
    usage=data.get('usage') if isinstance(data,dict) else None
    usage=usage if isinstance(usage,dict) else {}
    known=all(type(usage.get(k)) is int and 0 <= usage[k] <= 1_000_000_000 for k in ('prompt_tokens','completion_tokens'))
    return {'model':model,'usageReported':known,'usage':{
        'inputTokens':tokens(usage.get('prompt_tokens')),'outputTokens':tokens(usage.get('completion_tokens'))}}


def with_usage(error, metadata):
    error.model_result=metadata
    return error


async def record(programs, project, result, profile, skill, status='completed'):
    usage=result.get('usage') or {}
    incoming,outgoing=tokens(usage.get('inputTokens')),tokens(usage.get('outputTokens'))
    known=result.get('usageReported',all(k in usage for k in ('inputTokens','outputTokens')))
    await programs.query('execute', '''INSERT INTO llm_usage_events
        (id,owner,project_id,provider,model,skill,input_tokens,output_tokens,usage_known,status)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (str(uuid4()),project['owner'],project['id'],profile['provider'],str(result.get('model') or profile.get('model') or '')[:200],
         skill,incoming,outgoing,bool(known),status))
    return {'inputTokens':incoming,'outputTokens':outgoing}


async def summary(db, owner, days, timezone):
    rows=await db('all', '''WITH bounds AS (
        SELECT (now() AT TIME ZONE %s)::date AS today
    ), daily AS (
        SELECT (created AT TIME ZONE %s)::date AS day,
            sum(input_tokens)::bigint AS input_tokens,sum(output_tokens)::bigint AS output_tokens,
            sum(CASE WHEN lower(model) IN ('gigachat/gigachat-3-pro','gigachat-3-pro') THEN input_tokens ELSE 0 END)::bigint AS priced_input,
            sum(CASE WHEN lower(model) IN ('gigachat/gigachat-3-pro','gigachat-3-pro') THEN output_tokens ELSE 0 END)::bigint AS priced_output,
            count(*)::int AS calls,count(*) FILTER(WHERE NOT usage_known)::int AS unknown_calls,
            count(*) FILTER(WHERE status='failed')::int AS failed_calls
        FROM llm_usage_events,bounds WHERE owner=%s
        AND created >= ((today-(%s-1))::timestamp AT TIME ZONE %s)
        GROUP BY 1
    ) SELECT to_char(d.day,'YYYY-MM-DD') AS date,
        coalesce(s.input_tokens,0) AS "inputTokens",coalesce(s.output_tokens,0) AS "outputTokens",
        coalesce(s.calls,0) AS calls,coalesce(s.unknown_calls,0) AS "unknownCalls",
        coalesce(s.failed_calls,0) AS "failedCalls",coalesce(s.priced_input,0) AS priced_input,coalesce(s.priced_output,0) AS priced_output
    FROM bounds,generate_series(today-(%s-1),today,'1 day') AS d(day)
    LEFT JOIN daily s ON s.day=d.day::date ORDER BY d.day''',(timezone,timezone,owner,days,timezone,days))
    total=await db('one','''SELECT coalesce(sum(input_tokens),0)::bigint AS "inputTokens",
        coalesce(sum(output_tokens),0)::bigint AS "outputTokens",count(*)::int AS calls
        FROM llm_usage_events WHERE owner=%s''',(owner,))
    legacy=await db('one','''SELECT coalesce(sum(input_tokens),0)::bigint AS "inputTokens",
        coalesce(sum(output_tokens),0)::bigint AS "outputTokens",coalesce(sum(calls),0)::bigint AS calls
        FROM llm_usage_baselines WHERE owner=%s''',(owner,))
    priced=await db('one',"""SELECT coalesce(sum(input_tokens),0)::bigint AS incoming,coalesce(sum(output_tokens),0)::bigint AS outgoing
        FROM llm_usage_events WHERE owner=%s AND lower(model) IN ('gigachat/gigachat-3-pro','gigachat-3-pro')""",(owner,))
    period_in=sum(x['priced_input'] for x in rows);period_out=sum(x['priced_output'] for x in rows)
    for row in rows:
        row['cost']=cost(row.pop('priced_input'),row.pop('priced_output'))
    all_time={k:total[k]+legacy[k] for k in total}
    return {'days':rows,'timezone':timezone,'periodDays':days,'allTime':all_time,'legacy':legacy,
        'pricing':{'currency':'RUB','model':'GigaChat/GigaChat-3-Pro','inputPerMillion':float(INPUT_RATE),'outputPerMillion':float(OUTPUT_RATE),
                   'period':cost(period_in,period_out),'allTime':cost(priced['incoming'],priced['outgoing']),
                   'unpricedPeriodTokens':sum(x['inputTokens']+x['outputTokens'] for x in rows)-period_in-period_out,
                   'unpricedAllTimeTokens':all_time['inputTokens']+all_time['outputTokens']-priced['incoming']-priced['outgoing']}}

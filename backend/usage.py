"""Durable per-account model usage. No prompts, keys or response content are stored."""
from uuid import uuid4


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
            count(*)::int AS calls,count(*) FILTER(WHERE NOT usage_known)::int AS unknown_calls,
            count(*) FILTER(WHERE status='failed')::int AS failed_calls
        FROM llm_usage_events,bounds WHERE owner=%s
        AND created >= ((today-(%s-1))::timestamp AT TIME ZONE %s)
        GROUP BY 1
    ) SELECT to_char(d.day,'YYYY-MM-DD') AS date,
        coalesce(s.input_tokens,0) AS "inputTokens",coalesce(s.output_tokens,0) AS "outputTokens",
        coalesce(s.calls,0) AS calls,coalesce(s.unknown_calls,0) AS "unknownCalls",
        coalesce(s.failed_calls,0) AS "failedCalls"
    FROM bounds,generate_series(today-(%s-1),today,'1 day') AS d(day)
    LEFT JOIN daily s ON s.day=d.day::date ORDER BY d.day''',(timezone,timezone,owner,days,timezone,days))
    total=await db('one','''SELECT coalesce(sum(input_tokens),0)::bigint AS "inputTokens",
        coalesce(sum(output_tokens),0)::bigint AS "outputTokens",count(*)::int AS calls
        FROM llm_usage_events WHERE owner=%s''',(owner,))
    legacy=await db('one','''SELECT coalesce(sum(input_tokens),0)::bigint AS "inputTokens",
        coalesce(sum(output_tokens),0)::bigint AS "outputTokens",coalesce(sum(calls),0)::bigint AS calls
        FROM llm_usage_baselines WHERE owner=%s''',(owner,))
    return {'days':rows,'timezone':timezone,'periodDays':days,'allTime':{k:total[k]+legacy[k] for k in total},'legacy':legacy}

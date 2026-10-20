"""Typed external boundaries; internal arithmetic is not delegated to the LLM."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,StrictInt


class Requirements(BaseModel):
    model_config=ConfigDict(extra='allow')
    type:Literal['dpp','general']|None=None
    totalHours:StrictInt|None=Field(default=None,ge=16,le=10000)
    audience:str|None=None
    entryLevel:str|None=None
    format:str|None=None
    assessment:str|None=None
    title:str|None=None
    finalHours:StrictInt|None=Field(default=None,ge=1)
    weeks:StrictInt|None=Field(default=None,ge=1,le=1000)
    minPracticeHours:StrictInt=Field(default=0,ge=0)
    testQuestionCount:StrictInt|None=Field(default=None,ge=1,le=1000)
    selfStudyOnly:bool=False
    sessionHours:StrictInt|None=Field(default=None,ge=1,le=24)
    sessionsPerWeek:StrictInt|None=Field(default=None,ge=1,le=7)
    maxHoursPerDay:StrictInt|None=Field(default=None,ge=1,le=24)
    daysPerWeek:StrictInt=Field(default=5,ge=1,le=7)
    durationMonths:StrictInt|None=Field(default=None,ge=1,le=24)
    approximateDuration:bool=False
    portfolioItems:StrictInt|None=Field(default=None,ge=1,le=100)
    currentControl:Literal['test','interview','mixed']='test'
    requiredTopics:list[str]=Field(default_factory=list,max_length=40)
    slidesForSessions:StrictInt|None=Field(default=None,ge=1,le=100)
    slidesForTopics:list[str]=Field(default_factory=list,max_length=40)
    russiaOnlyServices:bool=False


class Question(BaseModel):
    field:str=Field(min_length=1,max_length=80)
    question:str=Field(min_length=1,max_length=2000)


class Intake(BaseModel):
    requirements:Requirements
    questions:list[Question]=Field(default_factory=list,max_length=5)
    notes:list[str]=Field(default_factory=list)
    skeleton:dict|None=None


class StandardLink(BaseModel):
    code:str
    title:str=''
    functionCode:str
    url:str=''
    status:Literal['unverified','scope_requires_expert_review']='unverified'


class Competency(BaseModel):
    id:str=Field(min_length=1,max_length=80)
    title:str=Field(min_length=1,max_length=300)
    knowledge:str=Field(min_length=1,max_length=3000)
    abilities:str=Field(min_length=1,max_length=3000)
    skills:str=Field(min_length=1,max_length=3000)
    standard:StandardLink|None=None


class OutlineTopic(BaseModel):
    title:str=Field(min_length=1,max_length=300)
    competencyIds:list[str]=Field(min_length=1,max_length=40)
    weight:int=Field(default=1,ge=1,le=100)


class OutlineModule(BaseModel):
    title:str=Field(min_length=1,max_length=300)
    topics:list[OutlineTopic]=Field(min_length=1,max_length=12)


class Outline(BaseModel):
    title:str=Field(min_length=1,max_length=300)
    goal:str=Field(min_length=1,max_length=4000)
    competencies:list[Competency]=Field(min_length=1,max_length=40)
    modules:list[OutlineModule]=Field(min_length=1,max_length=12)
    assumptions:list[str]=Field(default_factory=list)


class LinkedMaterial(BaseModel):
    id:str=Field(min_length=1,max_length=80)
    topicId:str=Field(min_length=1,max_length=80)
    competencyIds:list[str]=Field(min_length=1)


class TestQuestion(LinkedMaterial):
    text:str=Field(min_length=1,max_length=4000)
    options:list[str]=Field(min_length=2,max_length=10)
    answer:StrictInt=Field(ge=0,le=9)
    explanation:str=Field(min_length=1,max_length=4000)


class Criterion(BaseModel):
    title:str=Field(min_length=1,max_length=1000)
    points:StrictInt=Field(ge=1,le=100)


class Seminar(LinkedMaterial):
    title:str
    task:str
    deliverable:str
    criteria:list[Criterion]=Field(min_length=2)


class Slide(BaseModel):
    title:str=Field(min_length=1,max_length=180)
    text:str=Field(min_length=1,max_length=650)
    notes:str=Field(min_length=1,max_length=10000)


class Lecture(LinkedMaterial):
    title:str
    plan:str
    content:str=Field(min_length=200,max_length=60000)
    slides:list[Slide]=Field(min_length=1,max_length=20)


class LessonMaterial(BaseModel):
    moduleId:str
    summary:str=Field(min_length=1)
    methodology:str=Field(min_length=1)
    questions:list[TestQuestion]
    seminars:list[Seminar]=Field(min_length=1)
    lectures:list[Lecture]=Field(min_length=1)
    sources:list[dict]=Field(default_factory=list)


class Interview(LinkedMaterial):
    text:str=Field(min_length=1,max_length=4000)
    expectedAnswer:str=Field(min_length=1,max_length=6000)
    criteria:list[Criterion]=Field(min_length=2)


class LessonAssessment(BaseModel):
    questions:list[TestQuestion]
    seminars:list[Seminar]=Field(min_length=1)
    interviews:list[Interview]=Field(default_factory=list)


class PortfolioItem(BaseModel):
    title:str=Field(min_length=1,max_length=300)
    requirements:str=Field(min_length=1,max_length=6000)


class FinalAssessment(BaseModel):
    title:str=Field(min_length=1,max_length=300)
    task:str=Field(min_length=1,max_length=20000)
    deliverable:str=Field(min_length=1,max_length=6000)
    criteria:list[Criterion]=Field(min_length=2,max_length=30)
    items:list[PortfolioItem]=Field(default_factory=list,max_length=100)

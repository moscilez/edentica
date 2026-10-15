export type Visibility = 'public' | 'private';
export type JobState = 'queued' | 'processing' | 'provider_processing' | 'ready' | 'error' | 'cancelled';
export interface User { id:string; name:string; email:string }
export type QuestionType='single'|'multiple'|'truefalse'|'matching'|'ordering'|'short'|'essay'|'practical'|'case';
export interface Question {type?:QuestionType;text:string;points?:number;options?:string[];prompts?:string[];answer:number|number[]|string}
export interface ModuleDraft { title:string; content:string; threshold:number; attempt_limit?:number; questions:Question[] }
export interface CourseSettings {exam_threshold:number;exam_limit:number;exam_minutes:number;duration_hours:number}
export interface CourseDraft {title:string; description:string; category:string; visibility:Visibility; modules:ModuleDraft[];settings?:CourseSettings}
export interface Course extends Omit<CourseDraft,'modules'> {id:string; owner:string; published:0|1; created:string}
export type PublicQuestion=Omit<Question,'answer'>;
export interface AssessmentResult {score:number;passed:boolean;pending?:boolean}
export interface GenerationJob {id:string;state:JobState;estimate:number;result:CourseDraft|null;error:string|null}
export interface MediaJob {id:string;course_id:string;module_id:string|null;kind:'speech'|'video';state:JobState;estimate:number;output_url:string|null;error:string|null}
export interface Certificate {id:string;name:string;title:string;author:string;created:string;revoked:boolean;reason?:string}
export interface Organization {id:string;name:string;owner:string;role:'owner'|'member'}

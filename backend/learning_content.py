"""Portable text blocks for Word/PDF. No HTML execution or remote image fetching."""
import re


def blocks(value):
    result=[];paragraph=[];code=None
    def flush():
        if paragraph:
            text=' '.join(paragraph);chunk=''
            for sentence in re.split(r'(?<=[.!?])\s+',text):
                if len(chunk)>400:
                    result.append(('paragraph',chunk.strip()));chunk=''
                chunk+=sentence+' '
            if chunk.strip():result.append(('paragraph',chunk.strip()))
            paragraph.clear()
    for raw in str(value or '').replace('\r','').split('\n'):
        line=raw.strip()
        if line.startswith('```'):
            flush()
            if code is not None:result.append(('code','\n'.join(code)));code=None
            else:code=[]
            continue
        if code is not None:code.append(raw);continue
        if not line:flush();continue
        heading=re.match(r'^#{1,3}\s+(.+)$',line)
        bullet=re.match(r'^(?:[-*•]|\d+[.)])\s+(.+)$',line)
        if heading:flush();result.append(('heading',heading[1]))
        elif bullet:flush();result.append(('bullet',bullet[1]))
        elif line.startswith('> '):flush();result.append(('callout',line[2:]))
        else:paragraph.append(line)
    flush()
    if code is not None:result.append(('code','\n'.join(code)))
    return result


def add_docx(doc,value,heading_level=3):
    from docx.shared import Pt,RGBColor
    for kind,text in blocks(value):
        if kind=='heading':doc.add_heading(text,heading_level)
        elif kind=='bullet':doc.add_paragraph(text,'List Bullet')
        else:
            p=doc.add_paragraph(text)
            p.paragraph_format.space_after=Pt(10)
            p.paragraph_format.line_spacing=1.35
            if kind=='code':
                for run in p.runs:run.font.name='Consolas';run.font.size=Pt(10)
            elif kind=='callout':
                for run in p.runs:run.italic=True;run.font.color.rgb=RGBColor.from_string('6944B7')

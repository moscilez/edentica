from io import BytesIO
import html
from fastapi.responses import Response
from docx import Document
from docx.shared import Pt
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
import os

from .platform import lessons
from .programs_helpers import ensure
from .slides import program_pptx


def export_lesson(program,lesson_id,format):
    lesson = next((l for l in lessons(program) if l["id"] == lesson_id),None)
    ensure(lesson,"Урок не найден",404)
    output=BytesIO()
    if format == "docx":
        doc=Document()
        doc.styles['Normal'].font.name='Arial'
        doc.styles['Normal'].font.size=Pt(12)
        doc.add_heading(lesson['title'],0)
        doc.add_paragraph('Эдентика · Черновик для экспертной проверки')
        for paragraph in lesson['text'].split('\n'):
            doc.add_paragraph(paragraph)
        doc.save(output)
        mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif format == "pptx":
        single={"skeleton":program['skeleton'],"materials":{"one":{"lectures":[{"slides":lesson['slides']}]}}}
        output.write(program_pptx(single))
        mime='application/vnd.openxmlformats-officedocument.presentationml.presentation'
    elif format in ("pdf","slides-pdf"):
        font=os.getenv('CERTIFICATE_FONT') or ('C:/Windows/Fonts/arial.ttf' if os.name=='nt' else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
        if 'Edentica' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('Edentica',font))
        styles=getSampleStyleSheet()
        styles.add(ParagraphStyle(name='BodyRu',fontName='Edentica',fontSize=12,leading=20,spaceAfter=12))
        styles.add(ParagraphStyle(name='TitleRu',fontName='Edentica',fontSize=22,leading=30,spaceAfter=20))
        story=[]
        if format=='slides-pdf':
            for i,s in enumerate(lesson['slides']):
                if i:story.append(PageBreak())
                story.extend([Paragraph(html.escape(s['title']),styles['TitleRu']),Paragraph(html.escape(s['text']).replace('\n','<br/>'),styles['BodyRu'])])
        else:
            story.append(Paragraph(html.escape(lesson['title']),styles['TitleRu']))
            story.extend(Paragraph(html.escape(t).replace('\n','<br/>'),styles['BodyRu']) for t in lesson['text'].split('\n\n'))
        SimpleDocTemplate(output,pagesize=landscape(A4) if format=='slides-pdf' else A4).build(story)
        mime='application/pdf'
    else:
        ensure(False,"Неподдерживаемый формат")
    extension='pdf' if format=='slides-pdf' else format
    return Response(output.getvalue(),media_type=mime,headers={'Content-Disposition':f'attachment; filename="lesson.{extension}"'})

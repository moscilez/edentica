from io import BytesIO
from docx import Document
from pptx import Presentation
from backend.learning_content import blocks,add_docx
from backend.slides import program_pptx


def test_readable_blocks_and_docx_preserve_headings_code_and_lists():
    text='## Пример\n\nОбъяснение.\n\n- Первый шаг\n- Второй шаг\n\n```python\nprint("<test>")\n    value = 2\n```\n\n> Проверьте результат'
    result=blocks(text)
    assert [x[0] for x in result]==['heading','paragraph','bullet','bullet','code','callout']
    assert '    value = 2' in result[4][1]
    doc=Document();add_docx(doc,text)
    assert doc.paragraphs[0].style.name=='Heading 3'
    assert doc.paragraphs[2].style.name=='List Bullet'
    assert '<test>' in doc.paragraphs[4].text


def test_slide_layouts_are_distinct_and_keep_all_content():
    slides=[{'layout':layout,'title':layout,'text':'- Первый шаг\n- Второй шаг','notes':'Пояснение'} for layout in ['concept','steps','comparison','example','summary']]
    p={'skeleton':{'title':'Курс'},'materials':{'m':{'lectures':[{'slides':slides}]}}}
    deck=Presentation(BytesIO(program_pptx(p)))
    assert len(deck.slides)==6
    for slide in list(deck.slides)[1:]:
        text=' '.join(s.text for s in slide.shapes if s.has_text_frame)
        assert 'Первый шаг' in text and 'Второй шаг' in text
    assert len(deck.slides[2].shapes)!=len(deck.slides[1].shapes)

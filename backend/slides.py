"""Portable editable PPTX export without host-specific Node packages."""
from io import BytesIO

from fastapi import HTTPException
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt


def program_pptx(program, module_id=None, topic_ids=None):
    materials = program.get("materials", {})
    if module_id and module_id not in materials:
        raise HTTPException(409, "Материалы модуля ещё не готовы")
    modules = [materials[module_id]] if module_id else list(materials.values())
    slides = [s for m in modules for lecture in m.get("lectures", []) if topic_ids is None or lecture.get('topicId') in topic_ids for s in lecture.get("slides", [])]
    if not 1 <= len(slides) <= 300:
        raise HTTPException(422, "Выгружайте отдельный модуль: допустимо 1–300 слайдов")
    skeleton = program["skeleton"]
    slides.insert(0, {"title": skeleton["title"], "text": "Черновик для экспертной проверки. " + skeleton.get("audience", ""),
                      "notes": "Содержание требует утверждения человеком."})
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    for index, content in enumerate(slides):
        # Split lengthy model text into additional slides instead of clipping it.
        text = str(content.get("text", ""))
        chunks = [text[i:i + 1000] for i in range(0, len(text), 1000)] or [""]
        for part, chunk in enumerate(chunks):
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = RGBColor.from_string("F7F8FA")

            def box(value, x, y, width, height, size, color, bold=False):
                frame = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(width), Inches(height)).text_frame
                frame.word_wrap = True
                frame.text = str(value)
                for paragraph in frame.paragraphs:
                    paragraph.font.name = "DejaVu Sans"
                    paragraph.font.size = Pt(size)
                    paragraph.font.bold = bold
                    paragraph.font.color.rgb = RGBColor.from_string(color)
                return frame

            box("ЭДЕНТИКА · ЧЕРНОВИК", .6, .3, 12, .4, 12, "7A52E9")
            title = str(content.get("title", ""))
            if part:
                title += " · продолжение"
            box(title, .6, 1, 12, 1.5, 20 if len(title)>150 else 26 if len(title) > 90 else 32, "202126", True)
            box(chunk, .6, 2.6, 12, 4.15, 20, "202126")
            box(str(len(deck.slides)), 12, 7, .7, .3, 11, "727780")
            slide.notes_slide.notes_text_frame.text = str(content.get("notes", ""))
    output = BytesIO()
    deck.save(output)
    return output.getvalue()

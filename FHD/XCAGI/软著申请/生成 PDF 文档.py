"""
生成软著申请用的 PDF 源代码文档
- 前 30 页（每页 50 行）
- 后 30 页（每页 50 行）
- 总共 60 页
- 每页带页眉：软件名 + 版本号；每页带页脚：第 X 页 / 共 Y 页
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from datetime import datetime


def _find_cn_font() -> str | None:
    """找一个能用的中文字体（macOS / Windows / Linux 都行）"""
    candidates = [
        '/System/Library/Fonts/STHeiti Medium.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
        '/System/Library/Fonts/PingFang.ttc',
        '/Library/Fonts/Songti.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        r'C:\Windows\Fonts\simhei.ttf',
        r'C:\Windows\Fonts\simsun.ttc',
        r'C:\Windows\Fonts\msyh.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _header_footer(canvas, doc, *, software_name, version, copyright_holder):
    """每页的页眉页脚"""
    canvas.saveState()

    font_path = _find_cn_font()
    if font_path:
        try:
            from reportlab.pdfbase.ttfonts import TTFont as _T
            pdfmetrics.registerFont(_T('HeaderCN', font_path))
            header_font = 'HeaderCN'
        except Exception:
            header_font = 'Helvetica'
    else:
        header_font = 'Helvetica'

    # 页眉：左 软件名 版本  ｜  右 共 60 页
    canvas.setFont(header_font, 9)
    canvas.setFillColor(colors.grey)
    canvas.drawString(2.5 * cm, A4[1] - 1.5 * cm, f'{software_name} {version}')
    canvas.drawRightString(A4[0] - 2.5 * cm, A4[1] - 1.5 * cm, '程序鉴别材料')
    canvas.line(2.5 * cm, A4[1] - 1.6 * cm, A4[0] - 2.5 * cm, A4[1] - 1.6 * cm)

    # 页脚：左 著作权人  ｜  中 第 X 页 / 共 60 页  ｜  右 日期
    canvas.setFont(header_font, 9)
    canvas.drawString(
        2.5 * cm, 1.5 * cm,
        f'著作权人：{copyright_holder}',
    )
    canvas.drawCentredString(
        A4[0] / 2, 1.5 * cm,
        f'— 第 {doc.page} 页 / 共 60 页 —',
    )
    canvas.drawRightString(
        A4[0] - 2.5 * cm, 1.5 * cm,
        datetime.now().strftime('%Y-%m-%d'),
    )
    canvas.line(2.5 * cm, 1.7 * cm, A4[0] - 2.5 * cm, 1.7 * cm)
    canvas.restoreState()


def _read_source_file(file_path: str) -> list[str]:
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.readlines()


def _line_to_paragraph(line: str) -> str:
    line = line.rstrip()
    return line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def generate_pdf(output_file: str, source_file: str,
                 software_name: str = 'XCAGI 企业 AI 员工平台',
                 version: str = 'V9.0',
                 copyright_holder: str = '李佳泷'):
    """生成源代码 PDF 文档

    - 取前 30 页 + 后 30 页，每页 50 行
    - 每页带页眉「软件名 版本」+ 页脚「著作权人 + 页码 + 日期」
    """
    font_path = _find_cn_font()
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont('BodyCN', font_path))
            font_name = 'BodyCN'
        except Exception as e:
            print(f'字体注册失败 {font_path}: {e}')
            font_name = 'Helvetica'
    else:
        print('未找到中文字体，PDF 中文可能显示为方块')
        font_name = 'Helvetica'

    doc = SimpleDocTemplate(
        output_file,
        pagesize=A4,
        leftMargin=2.0 * cm,
        rightMargin=2.0 * cm,
        topMargin=2.4 * cm,
        bottomMargin=2.4 * cm,
    )

    styles = getSampleStyleSheet()
    code_style = ParagraphStyle(
        name='CodeStyle',
        parent=styles['Code'],
        fontName=font_name,
        fontSize=8.5,
        leading=11,
        alignment=TA_LEFT,
        spaceBefore=0,
        spaceAfter=0,
    )

    all_lines = _read_source_file(source_file)
    total_lines = len(all_lines)

    lines_per_page = 50
    total_pages = (total_lines + lines_per_page - 1) // lines_per_page

    print(f'总行数：{total_lines}')
    print(f'总页数：{total_pages}')
    print(f'每页行数：{lines_per_page}')

    first_n = min(30, total_pages)
    last_n = min(30, total_pages)
    start_last = max(0, total_pages - last_n)

    story = []

    # 封面页（不计入 60 页，只放软件名 + 说明）
    story.append(Spacer(1, 6 * cm))
    story.append(Paragraph(software_name, ParagraphStyle(
        name='TitleBig', fontName=font_name, fontSize=26, alignment=TA_CENTER,
    )))
    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph(f'程序鉴别材料 - 源代码文档（{version}）', ParagraphStyle(
        name='SubTitle', fontName=font_name, fontSize=14, alignment=TA_CENTER,
    )))
    story.append(Spacer(1, 2 * cm))
    story.append(Paragraph(
        f'本材料包含软件源代码前 {first_n} 页与后 {last_n} 页，共 {first_n + last_n} 页。',
        ParagraphStyle(name='Cover', fontName=font_name, fontSize=11, alignment=TA_CENTER),
    ))
    story.append(Paragraph(
        f'著作权人：{copyright_holder}',
        ParagraphStyle(name='Cover2', fontName=font_name, fontSize=11, alignment=TA_CENTER),
    ))
    story.append(Paragraph(
        f'开发完成日期：2026 年 5 月',
        ParagraphStyle(name='Cover3', fontName=font_name, fontSize=11, alignment=TA_CENTER),
    ))
    story.append(PageBreak())

    # 主体：前 30 页
    print(f'\n生成前 {first_n} 页...')
    for page_num in range(first_n):
        start_line = page_num * lines_per_page
        end_line = min((page_num + 1) * lines_per_page, total_lines)
        for line_num in range(start_line, end_line):
            story.append(Paragraph(_line_to_paragraph(all_lines[line_num]), code_style))
        story.append(PageBreak())

    # 主体：后 30 页
    print(f'\n生成后 {last_n} 页（从第 {start_last + 1} 页开始）...')
    for page_num in range(start_last, total_pages):
        start_line = page_num * lines_per_page
        end_line = min((page_num + 1) * lines_per_page, total_lines)
        for line_num in range(start_line, end_line):
            story.append(Paragraph(_line_to_paragraph(all_lines[line_num]), code_style))
        story.append(PageBreak())

    print('\n正在生成 PDF...')
    doc.build(
        story,
        onFirstPage=lambda c, d: _header_footer(
            c, d, software_name=software_name, version=version, copyright_holder=copyright_holder,
        ),
        onLaterPages=lambda c, d: _header_footer(
            c, d, software_name=software_name, version=version, copyright_holder=copyright_holder,
        ),
    )
    print(f'PDF 生成成功：{output_file}')


if __name__ == '__main__':
    software_name = 'XCAGI 企业 AI 员工平台'
    version = 'V9.0'
    copyright_holder = '李佳泷'
    source_file = '完整源代码.txt'
    output_file = f'源代码文档_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'

    if not os.path.exists(source_file):
        print(f'错误：找不到源代码文件 {source_file}')
        raise SystemExit(1)

    generate_pdf(
        output_file,
        source_file,
        software_name=software_name,
        version=version,
        copyright_holder=copyright_holder,
    )

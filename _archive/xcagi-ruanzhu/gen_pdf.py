"""
生成软著申请用的 PDF 源代码文档
- 前 30 页（每页 50 行）
- 后 30 页（每页 50 行）
- 总共 60 页
"""

import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_LEFT
from datetime import datetime


def read_source_file(file_path: str) -> list:
    """读取源代码文件的所有行"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.readlines()


def _find_cn_font():
    """找一个能用的中文字体"""
    candidates = [
        # macOS
        '/System/Library/Fonts/STHeiti Medium.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
        '/System/Library/Fonts/PingFang.ttc',
        '/Library/Fonts/Songti.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        # Windows
        r'C:\Windows\Fonts\simhei.ttf',
        r'C:\Windows\Fonts\simsun.ttc',
        r'C:\Windows\Fonts\msyh.ttc',
        # Linux
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def generate_pdf(output_file: str, source_file: str, software_name: str):
    """生成 PDF 文档"""

    font_path = _find_cn_font()
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont('CN', font_path))
            font_name = 'CN'
        except Exception as e:
            print(f'字体注册失败 {font_path}: {e}')
            font_name = 'Helvetica'
    else:
        print('未找到中文字体，PDF 中文可能显示为方块')
        font_name = 'Helvetica'
    
    doc = SimpleDocTemplate(
        output_file,
        pagesize=A4,
        leftMargin=2.5*cm,
        rightMargin=2.5*cm,
        topMargin=2.5*cm,
        bottomMargin=2.5*cm
    )
    
    styles = getSampleStyleSheet()
    code_style = ParagraphStyle(
        name='CodeStyle',
        parent=styles['Code'],
        fontName=font_name,
        fontSize=9,
        leading=10,
        alignment=TA_LEFT,
        spaceBefore=0,
        spaceAfter=0
    )
    
    all_lines = read_source_file(source_file)
    total_lines = len(all_lines)
    lines_per_page = 50
    total_pages = (total_lines + lines_per_page - 1) // lines_per_page
    
    print(f"总行数：{total_lines}")
    print(f"总页数：{total_pages}")
    
    first_pages = min(30, total_pages)
    last_pages = min(30, total_pages)
    
    story = []
    
    # 前 30 页
    print(f"生成前 {first_pages} 页...")
    for page_num in range(first_pages):
        start_line = page_num * lines_per_page
        end_line = min((page_num + 1) * lines_per_page, total_lines)
        
        header = f"{software_name} - 第 {page_num + 1} 页"
        story.append(Paragraph(header, code_style))
        story.append(Spacer(1, 0.1*cm))
        
        for i in range(start_line, end_line):
            line = all_lines[i].rstrip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            story.append(Paragraph(line, code_style))
        
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph("-" * 80, code_style))
        story.append(Spacer(1, 0.5*cm))
    
    # 后 30 页
    start_page = max(0, total_pages - last_pages)
    print(f"生成后 {last_pages} 页（从第 {start_page + 1} 页开始）...")
    
    for page_num in range(start_page, total_pages):
        start_line = page_num * lines_per_page
        end_line = min((page_num + 1) * lines_per_page, total_lines)
        
        header = f"{software_name} - 第 {page_num + 1} 页"
        story.append(Paragraph(header, code_style))
        story.append(Spacer(1, 0.1*cm))
        
        for i in range(start_line, end_line):
            line = all_lines[i].rstrip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            story.append(Paragraph(line, code_style))
        
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph("-" * 80, code_style))
        story.append(Spacer(1, 0.5*cm))
    
    print("生成 PDF...")
    doc.build(story)
    print(f"PDF 生成成功：{output_file}")


if __name__ == '__main__':
    software_name = "智能发货单生成系统"
    source_file = "完整源代码.txt"
    output_file = f"源代码文档_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    
    if not os.path.exists(source_file):
        print(f"错误：找不到 {source_file}")
        exit(1)
    
    generate_pdf(output_file, source_file, software_name)

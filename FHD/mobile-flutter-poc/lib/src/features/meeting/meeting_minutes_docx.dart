import 'dart:typed_data';

import 'package:archive/archive.dart';

class MeetingActionItem {
  const MeetingActionItem({
    required this.task,
    this.owner = '待确认',
    this.deadline = '待确认',
  });

  final String task;
  final String owner;
  final String deadline;
}

class MeetingMinutesDraft {
  const MeetingMinutesDraft({
    required this.title,
    required this.meetingDateText,
    required this.durationText,
    required this.transcript,
    this.participants = '',
    this.location = '',
    this.summary = '',
    this.discussionPoints = const [],
    this.decisions = const [],
    this.actionItems = const [],
  });

  final String title;
  final String meetingDateText;
  final String durationText;
  final String transcript;
  final String participants;
  final String location;
  final String summary;
  final List<String> discussionPoints;
  final List<String> decisions;
  final List<MeetingActionItem> actionItems;
}

class MeetingMinutesOutline {
  const MeetingMinutesOutline({
    required this.summary,
    required this.discussionPoints,
    required this.decisions,
    required this.actionItems,
  });

  final String summary;
  final List<String> discussionPoints;
  final List<String> decisions;
  final List<MeetingActionItem> actionItems;

  factory MeetingMinutesOutline.fromAssistantText(
    String raw, {
    required String transcript,
  }) {
    final sections = <String, List<String>>{};
    var current = '会议摘要';
    for (final sourceLine in raw.replaceAll('\r', '').split('\n')) {
      final line = sourceLine.trim();
      if (line.isEmpty) continue;
      final heading = RegExp(r'^【([^】]+)】$').firstMatch(line)?.group(1);
      if (heading != null) {
        current = heading.trim();
        continue;
      }
      sections.putIfAbsent(current, () => <String>[]).add(
            line.replaceFirst(RegExp(r'^(?:[-*]|\d+[.、])\s*'), '').trim(),
          );
    }

    final summaryLines = sections['会议摘要'] ?? const <String>[];
    final points = sections['讨论要点'] ?? const <String>[];
    final decisions = sections['决策事项'] ?? const <String>[];
    final actionLines = sections['待办事项'] ?? const <String>[];
    final actions = actionLines
        .where((line) => line.trim().isNotEmpty && line.trim() != '无')
        .map((line) {
      final fields = line
          .split(RegExp(r'[|｜]'))
          .map((value) => value.trim())
          .where((value) => value.isNotEmpty)
          .toList(growable: false);
      return MeetingActionItem(
        task: fields.isEmpty ? line : fields.first,
        owner: fields.length > 1 ? fields[1] : '待确认',
        deadline: fields.length > 2 ? fields[2] : '待确认',
      );
    }).toList(growable: false);

    final fallbackSummary = _fallbackSummary(transcript);
    return MeetingMinutesOutline(
      summary: summaryLines.join(' ').trim().isEmpty
          ? fallbackSummary
          : summaryLines.join(' ').trim(),
      discussionPoints: points.isEmpty
          ? _fallbackPoints(transcript)
          : List<String>.unmodifiable(points),
      decisions: List<String>.unmodifiable(
        decisions.where((line) => line != '无'),
      ),
      actionItems: List<MeetingActionItem>.unmodifiable(actions),
    );
  }

  static String _fallbackSummary(String transcript) {
    final clean = transcript.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (clean.length <= 180) return clean;
    return '${clean.substring(0, 180)}…';
  }

  static List<String> _fallbackPoints(String transcript) {
    final rows = transcript
        .split(RegExp(r'[。！？!?\n]+'))
        .map((row) => row.trim())
        .where((row) => row.length >= 4)
        .take(6)
        .toList(growable: false);
    return rows.isEmpty ? const ['请结合原始转写补充讨论要点。'] : rows;
  }
}

class MeetingMinutesDocxBuilder {
  static Uint8List build(MeetingMinutesDraft draft) {
    final archive = Archive()
      ..addFile(ArchiveFile.string('[Content_Types].xml', _contentTypes))
      ..addFile(ArchiveFile.string('_rels/.rels', _rootRelationships))
      ..addFile(ArchiveFile.string('docProps/core.xml', _coreProperties(draft)))
      ..addFile(ArchiveFile.string('docProps/app.xml', _appProperties))
      ..addFile(ArchiveFile.string('word/styles.xml', _styles))
      ..addFile(ArchiveFile.string('word/numbering.xml', _numbering))
      ..addFile(ArchiveFile.string(
        'word/_rels/document.xml.rels',
        _documentRelationships,
      ))
      ..addFile(ArchiveFile.string('word/document.xml', _document(draft)));
    return ZipEncoder().encodeBytes(archive);
  }

  static String _document(MeetingMinutesDraft draft) {
    final body = <String>[
      _paragraph(draft.title, style: 'Title', align: 'center'),
      _paragraph('由 XCAGI 小C助理生成', style: 'Subtitle', align: 'center'),
      _infoTable(draft),
      _paragraph('会议摘要', style: 'Heading1'),
      _paragraph(draft.summary.trim().isEmpty ? '暂无摘要。' : draft.summary),
      _paragraph('讨论要点', style: 'Heading1'),
      ..._bulletSection(draft.discussionPoints, emptyText: '暂无明确讨论要点。'),
      _paragraph('决策事项', style: 'Heading1'),
      ..._bulletSection(draft.decisions, emptyText: '暂无明确决策。'),
      _paragraph('待办事项', style: 'Heading1'),
      _actionTable(draft.actionItems),
      _paragraph('原始转写', style: 'Heading1'),
      ...draft.transcript
          .replaceAll('\r', '')
          .split('\n')
          .map((line) => line.trim())
          .where((line) => line.isNotEmpty)
          .map(_paragraph),
      _paragraph(
          '文档生成时间：${DateTime.now().toLocal().toIso8601String().substring(0, 19)}',
          style: 'Caption'),
      '<w:sectPr>'
          '<w:pgSz w:w="11906" w:h="16838"/>'
          '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
          'w:header="720" w:footer="720" w:gutter="0"/>'
          '</w:sectPr>',
    ];
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<w:body>${body.join()}</w:body></w:document>';
  }

  static List<String> _bulletSection(
    List<String> items, {
    required String emptyText,
  }) {
    if (items.isEmpty) return [_paragraph(emptyText)];
    return items.map(_bulletParagraph).toList(growable: false);
  }

  static String _infoTable(MeetingMinutesDraft draft) {
    final rows = <(String, String)>[
      ('会议时间', draft.meetingDateText),
      ('会议时长', draft.durationText),
      ('参会人员', draft.participants.trim().isEmpty ? '未填写' : draft.participants),
      ('会议地点', draft.location.trim().isEmpty ? '未填写' : draft.location),
    ];
    return '<w:tbl>'
        '<w:tblPr><w:tblW w:w="9026" w:type="dxa"/>'
        '<w:tblBorders>${_tableBorders()}</w:tblBorders></w:tblPr>'
        '<w:tblGrid><w:gridCol w:w="1800"/><w:gridCol w:w="7226"/></w:tblGrid>'
        '${rows.map((row) => '<w:tr>'
            '${_tableCell(row.$1, 1800, shaded: true, bold: true)}'
            '${_tableCell(row.$2, 7226)}'
            '</w:tr>').join()}'
        '</w:tbl>';
  }

  static String _actionTable(List<MeetingActionItem> items) {
    final rows =
        items.isEmpty ? const [MeetingActionItem(task: '暂无明确待办')] : items;
    return '<w:tbl>'
        '<w:tblPr><w:tblW w:w="9026" w:type="dxa"/>'
        '<w:tblBorders>${_tableBorders()}</w:tblBorders></w:tblPr>'
        '<w:tblGrid><w:gridCol w:w="4826"/><w:gridCol w:w="2100"/>'
        '<w:gridCol w:w="2100"/></w:tblGrid>'
        '<w:tr>${_tableCell('事项', 4826, shaded: true, bold: true)}'
        '${_tableCell('负责人', 2100, shaded: true, bold: true)}'
        '${_tableCell('截止时间', 2100, shaded: true, bold: true)}</w:tr>'
        '${rows.map((item) => '<w:tr>'
            '${_tableCell(item.task, 4826)}'
            '${_tableCell(item.owner, 2100)}'
            '${_tableCell(item.deadline, 2100)}'
            '</w:tr>').join()}'
        '</w:tbl>';
  }

  static String _tableCell(
    String text,
    int width, {
    bool shaded = false,
    bool bold = false,
  }) {
    return '<w:tc><w:tcPr><w:tcW w:w="$width" w:type="dxa"/>'
        '${shaded ? '<w:shd w:val="clear" w:fill="DCE6F1"/>' : ''}'
        '<w:tcMar><w:top w:w="80" w:type="dxa"/><w:left w:w="120" w:type="dxa"/>'
        '<w:bottom w:w="80" w:type="dxa"/><w:right w:w="120" w:type="dxa"/>'
        '</w:tcMar></w:tcPr>'
        '<w:p><w:r>${bold ? '<w:rPr><w:b/></w:rPr>' : ''}'
        '<w:t xml:space="preserve">${_xml(text)}</w:t></w:r></w:p></w:tc>';
  }

  static String _tableBorders() =>
      '<w:top w:val="single" w:sz="4" w:color="D0D5DD"/>'
      '<w:left w:val="single" w:sz="4" w:color="D0D5DD"/>'
      '<w:bottom w:val="single" w:sz="4" w:color="D0D5DD"/>'
      '<w:right w:val="single" w:sz="4" w:color="D0D5DD"/>'
      '<w:insideH w:val="single" w:sz="4" w:color="D0D5DD"/>'
      '<w:insideV w:val="single" w:sz="4" w:color="D0D5DD"/>';

  static String _paragraph(
    String text, {
    String? style,
    String? align,
  }) {
    return '<w:p><w:pPr>'
        '${style == null ? '' : '<w:pStyle w:val="$style"/>'}'
        '${align == null ? '' : '<w:jc w:val="$align"/>'}'
        '</w:pPr><w:r><w:t xml:space="preserve">${_xml(text)}</w:t></w:r></w:p>';
  }

  static String _bulletParagraph(String text) {
    return '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/>'
        '<w:numId w:val="1"/></w:numPr></w:pPr>'
        '<w:r><w:t xml:space="preserve">${_xml(text)}</w:t></w:r></w:p>';
  }

  static String _xml(String value) => value
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&apos;');

  static String _coreProperties(MeetingMinutesDraft draft) {
    final now = DateTime.now().toUtc().toIso8601String();
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:title>${_xml(draft.title)}</dc:title>'
        '<dc:creator>XCAGI 小C助理</dc:creator>'
        '<cp:lastModifiedBy>XCAGI 小C助理</cp:lastModifiedBy>'
        '<dcterms:created xsi:type="dcterms:W3CDTF">$now</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">$now</dcterms:modified>'
        '</cp:coreProperties>';
  }

  static const _contentTypes =
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
      '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
      '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
      '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
      '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
      '</Types>';

  static const _rootRelationships =
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
      '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
      '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
      '</Relationships>';

  static const _documentRelationships =
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
      '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
      '</Relationships>';

  static const _styles =
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
      '<w:docDefaults><w:rPrDefault><w:rPr>'
      '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="STHeiti" w:hint="eastAsia"/>'
      '<w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:rPrDefault>'
      '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
      '</w:docDefaults>'
      '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
      '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/>'
      '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
      '<w:pPr><w:spacing w:before="120" w:after="240"/></w:pPr>'
      '<w:rPr><w:b/><w:sz w:val="40"/><w:szCs w:val="40"/></w:rPr></w:style>'
      '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/>'
      '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/>'
      '<w:rPr><w:color w:val="667085"/><w:sz w:val="20"/></w:rPr></w:style>'
      '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
      '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
      '<w:pPr><w:spacing w:before="300" w:after="140"/><w:outlineLvl w:val="0"/></w:pPr>'
      '<w:rPr><w:b/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>'
      '<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="Caption"/>'
      '<w:basedOn w:val="Normal"/><w:rPr><w:color w:val="98A2B3"/><w:sz w:val="18"/></w:rPr></w:style>'
      '</w:styles>';

  static const _numbering =
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
      '<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/>'
      '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/>'
      '<w:lvlText w:val="•"/><w:lvlJc w:val="left"/>'
      '<w:pPr><w:tabs><w:tab w:val="num" w:pos="720"/></w:tabs>'
      '<w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>'
      '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
      '</w:numbering>';

  static const _appProperties =
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
      'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
      '<Application>XCAGI Mobile</Application><DocSecurity>0</DocSecurity>'
      '<ScaleCrop>false</ScaleCrop><Company>XCAGI</Company>'
      '<AppVersion>10.0</AppVersion></Properties>';
}

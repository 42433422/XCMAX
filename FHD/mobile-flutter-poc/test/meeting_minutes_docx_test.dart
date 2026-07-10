import 'dart:convert';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/meeting/meeting_minutes_docx.dart';

void main() {
  test('meeting minutes outline parses structured assistant response', () {
    const response = '''
【会议摘要】
团队确认移动端小C升级方向。
【讨论要点】
- 增加舒适空白态
- 新增会议纪要
【决策事项】
- 本周交付 Android 版本
【待办事项】
- 完成录音转写｜张三｜周五
''';

    final outline = MeetingMinutesOutline.fromAssistantText(
      response,
      transcript: '团队讨论了小C升级。',
    );

    expect(outline.summary, '团队确认移动端小C升级方向。');
    expect(outline.discussionPoints, hasLength(2));
    expect(outline.decisions.single, '本周交付 Android 版本');
    expect(outline.actionItems.single.task, '完成录音转写');
    expect(outline.actionItems.single.owner, '张三');
    expect(outline.actionItems.single.deadline, '周五');
  });

  test('meeting minutes builder creates a valid structured docx package', () {
    final bytes = MeetingMinutesDocxBuilder.build(
      const MeetingMinutesDraft(
        title: '产品周会纪要',
        meetingDateText: '2026-07-10 21:00',
        durationText: '32:18',
        participants: '张三、李四',
        location: '线上会议',
        summary: '确认小C助理舒适版与会议纪要功能。',
        discussionPoints: ['小C定位为总助理', '会议录音转写生成 Word'],
        decisions: ['优先交付 Android 真机版'],
        actionItems: [
          MeetingActionItem(
            task: '完成真机验收',
            owner: '张三',
            deadline: '周五',
          ),
        ],
        transcript: '大家确认本周完成移动端更新。\n会议纪要需要可以分享 Word。',
      ),
    );
    final archive = ZipDecoder().decodeBytes(bytes);
    final names = archive.files.map((file) => file.name).toSet();

    expect(names, contains('[Content_Types].xml'));
    expect(names, contains('word/document.xml'));
    expect(names, contains('word/styles.xml'));
    expect(names, contains('word/numbering.xml'));

    final document = utf8.decode(
      archive.findFile('word/document.xml')!.content,
    );
    expect(document, contains('产品周会纪要'));
    expect(document, contains('会议摘要'));
    expect(document, contains('原始转写'));
    expect(document, contains('<w:pgSz w:w="11906" w:h="16838"/>'));
    expect(document, contains('<w:tblW w:w="9026" w:type="dxa"/>'));
    expect(document, contains('<w:numId w:val="1"/>'));
  });
}

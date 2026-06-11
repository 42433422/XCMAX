# -*- coding: utf-8 -*-

from app.application.demo_chat_fallback import try_demo_attendance_reply


def test_demo_attendance_leave_query():
    text = try_demo_attendance_reply("今天谁请假了？")
    assert text
    assert "请假" in text


def test_demo_attendance_greeting():
    text = try_demo_attendance_reply("你好")
    assert text
    assert "考勤" in text

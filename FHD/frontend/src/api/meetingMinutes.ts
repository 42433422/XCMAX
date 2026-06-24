/**
 * 会议纪要 SSOT API 客户端：三级派生（剧本式 → 架构图式 → 说人话）。
 * 录音转写复用 /api/voice/transcribe；三级生成走 /api/meetings/generate-all。
 */
import { api } from './core';

export interface MeetingLevelDef {
  id: string;
  label: string;
  short?: string;
  derives_from: string;
  render?: string;
  hint?: string;
}

export interface MeetingLevelsConfig {
  version: number;
  levels: MeetingLevelDef[];
}

export interface MeetingMinute {
  id: number;
  title: string | null;
  status: 'pending' | 'generating' | 'completed' | 'degraded' | 'failed';
  source_hash: string;
  level1_script: string | null;
  level2_architecture: string | null;
  level3_plain: string | null;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

interface ApiEnvelope<T> {
  success: boolean;
  data: T;
  message?: string;
}

interface TranscribeData {
  text: string;
  language?: string;
  audio_seconds?: number;
}

function mimeExtension(mime: string): string {
  const m = String(mime || '').toLowerCase();
  if (m.includes('webm')) return 'webm';
  if (m.includes('ogg')) return 'ogg';
  if (m.includes('mp4') || m.includes('m4a')) return 'm4a';
  if (m.includes('wav') || m.includes('wave')) return 'wav';
  return 'bin';
}

export const meetingMinutesApi = {
  /** 三级定义（标签/派生关系），用于渲染 Tab */
  async getLevels(): Promise<MeetingLevelsConfig> {
    const res = await api.get<ApiEnvelope<MeetingLevelsConfig>>('/api/meetings/levels');
    return res.data;
  },

  /** 一次性生成三级会议纪要 */
  async generateAll(rawTranscript: string, title?: string): Promise<MeetingMinute> {
    const res = await api.post<ApiEnvelope<MeetingMinute>>('/api/meetings/generate-all', {
      raw_transcript: rawTranscript,
      title: title || null,
    });
    return res.data;
  },

  async getMinute(id: number): Promise<MeetingMinute> {
    const res = await api.get<ApiEnvelope<MeetingMinute>>(`/api/meetings/${id}`);
    return res.data;
  },

  async listMinutes(page = 1, perPage = 20): Promise<{ items: MeetingMinute[]; page: number; per_page: number }> {
    const res = await api.get<ApiEnvelope<{ items: MeetingMinute[]; page: number; per_page: number }>>(
      '/api/meetings',
      { page, per_page: perPage },
    );
    return res.data;
  },

  /** 录音 blob → 文本（复用既有 ASR 端点） */
  async transcribe(blob: Blob, mimeType = ''): Promise<string> {
    const ext = mimeExtension(blob.type || mimeType);
    const form = new FormData();
    form.append('file', blob, `meeting.${ext}`);
    const res = await api.post<ApiEnvelope<TranscribeData>>('/api/voice/transcribe', form);
    return String(res?.data?.text || '').trim();
  },
};

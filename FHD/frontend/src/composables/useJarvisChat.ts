import { ref, computed, onUnmounted } from 'vue';
import { useJarvisChatStore } from '@/stores/jarvisChat';
import { asRecord, asArray, asString, asBoolean, asDisposable } from '@/utils/typeGuards'

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onstart: (() => void) | null;
  onresult: ((event: unknown) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

export function useJarvisChat(): unknown {
  const store = useJarvisChatStore();

  const isListening = ref(false);
  const recognition = ref<SpeechRecognitionLike | null>(null);

  const messages = computed(() => store.messages);
  const isRecording = computed(() => store.isRecording);
  const isPlaying = computed(() => store.isPlaying);
  const statusText = computed(() => store.statusText);
  const isCoreSpeaking = computed(() => store.isCoreSpeaking);

  const sendMessage = async (message: string) => {
    return await store.sendMessage(message);
  };

  const addMessage = (content: string, type: 'user' | 'ai' | 'task' = 'ai') => {
    store.addMessage(content, type);
  };

  const addTaskMessage = (content: string, taskData: unknown) => {
    store.addTaskMessage(content, taskData);
  };

  const startRecording = () => {
    const hasSpeech = 'webkitSpeechRecognition' in window || 'SpeechRecognition' in window;
    if (!hasSpeech) {
      console.warn('Speech recognition not supported');
      return;
    }

    const win = window as Window & {
      SpeechRecognition?: new () => SpeechRecognitionLike
      webkitSpeechRecognition?: new () => SpeechRecognitionLike
    }
    const SpeechRecognitionCtor = win.SpeechRecognition || win.webkitSpeechRecognition
    if (!SpeechRecognitionCtor) return
    recognition.value = new SpeechRecognitionCtor()
    recognition.value.lang = 'zh-CN';
    recognition.value.continuous = false;
    recognition.value.interimResults = false;

    recognition.value.onstart = () => {
      isListening.value = true;
      store.startRecording();
    };

    recognition.value.onresult = (event: unknown) => {
      const row = asRecord(event)
      const results = asArray(asRecord(asArray(row.results)[0])[0])
      const transcript = asString(results[0])
      store.stopRecording();
      if (transcript) {
        void sendMessage(transcript);
      }
    };

    recognition.value.onerror = (event: unknown) => {
      console.error('Speech recognition error:', asString(asRecord(event).error));
      store.stopRecording();
      isListening.value = false;
    };

    recognition.value.onend = () => {
      isListening.value = false;
      if (store.isRecording) {
        store.stopRecording();
      }
    };

    recognition.value.start();
  };

  const stopRecording = () => {
    if (recognition.value) {
      recognition.value.stop();
      recognition.value = null;
    }
    isListening.value = false;
    store.stopRecording();
  };

  const queueVoice = (text: string) => {
    store.queueVoice(text);
  };

  const speak = (text: string) => {
    store.queueVoice(text);
  };

  const setStatus = (text: string) => {
    store.setStatus(text);
  };

  const setCoreSpeaking = (speaking: boolean) => {
    store.setCoreSpeaking(speaking);
  };

  const clearMessages = () => {
    store.clearMessages();
  };

  const clearVoiceQueue = () => {
    store.clearVoiceQueue();
  };

  onUnmounted(() => {
    stopRecording();
  });

  return {
    messages,
    isRecording,
    isPlaying,
    isListening,
    statusText,
    isCoreSpeaking,
    sendMessage,
    addMessage,
    addTaskMessage,
    startRecording,
    stopRecording,
    queueVoice,
    speak,
    setStatus,
    setCoreSpeaking,
    clearMessages,
    clearVoiceQueue
  };
}

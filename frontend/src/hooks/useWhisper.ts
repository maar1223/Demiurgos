import { useCallback, useRef, useState, useEffect } from "react";

export type WhisperStatus = "idle" | "recording" | "transcribing";

interface UseWhisperOptions {
  onTranscribed?: (text: string) => void;
}

interface UseWhisperReturn {
  status: WhisperStatus;
  isRecording: boolean;
  isTranscribing: boolean;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  error: string | null;
}

/**
 * Hook for audio recording using the MediaRecorder API.
 *
 * When recording stops, the audio blob is captured. The `onTranscribed`
 * callback is called when a transcription backend becomes available.
 */
export function useWhisper({ onTranscribed }: UseWhisperOptions = {}): UseWhisperReturn {
  const [status, setStatus] = useState<WhisperStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const onTranscribedRef = useRef(onTranscribed);
  onTranscribedRef.current = onTranscribed;

  const startRecording = useCallback(async () => {
    setError(null);
    chunksRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const mimeType = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : "audio/mp4";

      const recorder = new MediaRecorder(stream, { mimeType });

      recorder.ondataavailable = (e: BlobEvent) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        // TODO: send audio blob to Whisper transcription endpoint
        // For now, notify via callback that recording stopped
        setStatus("idle");
      };

      recorder.onerror = () => {
        setError("Error al grabar audio");
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        setStatus("idle");
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setStatus("recording");
    } catch (err) {
      const msg =
        err instanceof DOMException && err.name === "NotAllowedError"
          ? "Permiso de micrófono denegado"
          : "No se pudo acceder al micrófono";
      setError(msg);
    }
  }, []);

  const stopRecording = useCallback(() => {
    if (
      mediaRecorderRef.current &&
      mediaRecorderRef.current.state !== "inactive"
    ) {
      setStatus("transcribing");
      mediaRecorderRef.current.stop();
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      }
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  return {
    status,
    isRecording: status === "recording",
    isTranscribing: status === "transcribing",
    startRecording,
    stopRecording,
    error,
  };
}

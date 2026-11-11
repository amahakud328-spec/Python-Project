"""Optional speech recognition and speech synthesis adapters."""

import threading


class VoiceFeatureError(RuntimeError):
    """Raised when speech input or output is unavailable."""


class VoiceController:
    """Runs microphone capture and text-to-speech away from Tk's UI thread."""

    def __init__(self, on_text, on_error, on_status) -> None:
        self.on_text = on_text
        self.on_error = on_error
        self.on_status = on_status
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._speech_engine = None

    def start_listening(self) -> None:
        if self._worker and self._worker.is_alive():
            raise VoiceFeatureError("Voice typing is already listening.")
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._listen, daemon=True)
        self._worker.start()

    def stop_listening(self) -> None:
        self._stop_event.set()
        self.on_status("Stopping microphone…")

    def _listen(self) -> None:
        try:
            import speech_recognition as sr
        except ImportError as error:
            self.on_error("Voice typing needs SpeechRecognition. Install it with pip.")
            return
        recognizer = sr.Recognizer()
        try:
            with sr.Microphone() as microphone:
                recognizer.adjust_for_ambient_noise(microphone, duration=0.5)
                self.on_status("Listening… Speak a phrase, then pause.")
                while not self._stop_event.is_set():
                    try:
                        audio = recognizer.listen(
                            microphone, timeout=1, phrase_time_limit=12
                        )
                    except sr.WaitTimeoutError:
                        continue
                    try:
                        transcript = recognizer.recognize_google(audio)
                    except sr.UnknownValueError:
                        self.on_status("Speech was not clear; keep speaking.")
                        continue
                    except sr.RequestError as error:
                        self.on_error(f"Speech recognition service error: {error}")
                        return
                    if transcript:
                        self.on_text(transcript)
        except (OSError, AttributeError) as error:
            self.on_error(
                f"Microphone unavailable or permission denied: {error}\n"
                "Check Windows microphone privacy settings and install PyAudio."
            )
            return
        finally:
            self.on_status("Microphone stopped.")

    def speak(self, text: str) -> None:
        if not text.strip():
            raise VoiceFeatureError("Select some text or enter text to read aloud.")
        self.stop_speech()

        def worker() -> None:
            try:
                import pyttsx3

                engine = pyttsx3.init()
                self._speech_engine = engine
                engine.say(text)
                engine.runAndWait()
            except (ImportError, RuntimeError, OSError) as error:
                self.on_error(f"Text-to-speech is unavailable: {error}")
            finally:
                self._speech_engine = None

        threading.Thread(target=worker, daemon=True).start()

    def stop_speech(self) -> None:
        if self._speech_engine is not None:
            try:
                self._speech_engine.stop()
            except RuntimeError as error:
                self.on_error(f"Could not stop speech playback: {error}")

    def shutdown(self) -> None:
        self.stop_listening()
        self.stop_speech()

import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone

from flask import Flask, render_template, request
from google.cloud import speech
from google.cloud import firestore


app = Flask(__name__)

speech_client = speech.SpeechClient()
db = firestore.Client(database="voicenotes")


LANGUAGE_NAMES = {
    "en-US": "English",
    "pl-PL": "Polish",
    "ru-RU": "Russian",
    "uk-UA": "Ukrainian",
    "de-DE": "German",
    "fr-FR": "French",
}


def convert_audio_to_wav(input_bytes):
    with tempfile.NamedTemporaryFile(delete=False) as input_file:
        input_file.write(input_bytes)
        input_path = input_file.name

    output_path = input_path + ".wav"

    try:
        command = [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-ac", "1",
            "-ar", "16000",
            "-sample_fmt", "s16",
            output_path,
        ]

        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        with open(output_path, "rb") as converted_file:
            return converted_file.read()

    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)


def create_simple_summary(text):
    if not text or text == "No speech was detected in the audio file.":
        return "No summary available."

    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [sentence.strip() for sentence in sentences if sentence.strip()]

    if len(sentences) == 0:
        return text[:220] + "..." if len(text) > 220 else text

    if len(sentences) == 1:
        return sentences[0]

    return " ".join(sentences[:2])


def get_language_config(selected_language):
    if selected_language == "auto":
        return speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code="en-US",
            alternative_language_codes=[
                "pl-PL",
                "ru-RU",
                "uk-UA",
                "de-DE",
                "fr-FR",
            ],
            enable_automatic_punctuation=True,
        )

    return speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code=selected_language,
        enable_automatic_punctuation=True,
    )


@app.route("/", methods=["GET", "POST"])
def index():
    transcript_text = None
    summary_text = None
    detected_language = None
    selected_language = "auto"
    error = None

    if request.method == "POST":
        uploaded_file = request.files.get("audio")
        recorded_audio = request.files.get("recorded_audio")
        selected_language = request.form.get("language", "auto")

        audio_file = recorded_audio if recorded_audio and recorded_audio.filename else uploaded_file

        if not audio_file or audio_file.filename == "":
            error = "Please upload an audio file or record audio first."
        else:
            try:
                original_audio = audio_file.read()
                converted_audio = convert_audio_to_wav(original_audio)

                audio = speech.RecognitionAudio(content=converted_audio)
                config = get_language_config(selected_language)

                response = speech_client.recognize(config=config, audio=audio)

                transcript_parts = []
                detected_language_code = None

                for result in response.results:
                    if result.alternatives:
                        transcript_parts.append(result.alternatives[0].transcript)

                    possible_language = getattr(result, "language_code", None)
                    if possible_language:
                        detected_language_code = possible_language

                transcript_text = " ".join(transcript_parts).strip()

                if not transcript_text:
                    transcript_text = "No speech was detected in the audio file."

                if detected_language_code:
                    detected_language = LANGUAGE_NAMES.get(detected_language_code, detected_language_code)
                elif selected_language != "auto":
                    detected_language = LANGUAGE_NAMES.get(selected_language, selected_language)
                else:
                    detected_language = "Not detected"

                summary_text = create_simple_summary(transcript_text)

                db.collection("transcripts").add({
                    "filename": audio_file.filename,
                    "text": transcript_text,
                    "summary": summary_text,
                    "selected_language": selected_language,
                    "detected_language": detected_language,
                    "created_at": datetime.now(timezone.utc),
                })

            except subprocess.CalledProcessError:
                error = "The uploaded or recorded audio could not be converted. Please try MP3, WAV, M4A, WEBM, or OGG."
            except Exception as e:
                error = f"Something went wrong: {str(e)}"

    return render_template(
        "index.html",
        transcript_text=transcript_text,
        summary_text=summary_text,
        detected_language=detected_language,
        selected_language=selected_language,
        error=error,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

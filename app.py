import os
import subprocess
import tempfile
from datetime import datetime, timezone

from flask import Flask, render_template, request
from google.cloud import speech
from google.cloud import firestore


app = Flask(__name__)

speech_client = speech.SpeechClient()
db = firestore.Client(database="voicenotes")


def convert_audio_to_wav(input_bytes):
    """
    Converts uploaded audio to WAV format required by Google Speech-to-Text:
    - mono
    - 16 kHz
    - 16-bit PCM
    """
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


@app.route("/", methods=["GET", "POST"])
def index():
    transcript_text = None
    error = None

    if request.method == "POST":
        uploaded_file = request.files.get("audio")

        if not uploaded_file or uploaded_file.filename == "":
            error = "Please upload an audio file."
        else:
            try:
                original_audio = uploaded_file.read()
                converted_audio = convert_audio_to_wav(original_audio)

                audio = speech.RecognitionAudio(content=converted_audio)

                config = speech.RecognitionConfig(
                    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                    sample_rate_hertz=16000,
                    language_code="en-US",
                )

                response = speech_client.recognize(
                    config=config,
                    audio=audio,
                )

                transcript_parts = []

                for result in response.results:
                    transcript_parts.append(result.alternatives[0].transcript)

                transcript_text = " ".join(transcript_parts)

                if not transcript_text:
                    transcript_text = "No speech was detected in the audio file."

                db.collection("transcripts").add({
                    "filename": uploaded_file.filename,
                    "text": transcript_text,
                    "created_at": datetime.now(timezone.utc),
                })

            except subprocess.CalledProcessError:
                error = "The uploaded file could not be converted. Please try MP3, WAV, M4A, WEBM, or OGG."
            except Exception as e:
                error = f"Something went wrong: {str(e)}"

    saved_transcripts = []

    try:
        transcripts_query = (
            db.collection("transcripts")
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(10)
        )

        for doc in transcripts_query.stream():
            saved_transcripts.append(doc.to_dict())

    except Exception:
        saved_transcripts = []

    return render_template(
        "index.html",
        transcript_text=transcript_text,
        error=error,
        saved_transcripts=saved_transcripts,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

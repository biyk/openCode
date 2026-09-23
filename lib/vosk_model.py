"""Загрузка моделей Vosk (скачивание при необходимости)."""

import os
import zipfile

import requests

# Модели Vosk (маленькие, ~50-60 МБ)
VOSK_MODELS = {
    "ru": {
        "name": "vosk-model-small-ru-0.22",
        "zip_url": "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip",
    },
    "en": {
        "name": "vosk-model-small-en-us-0.15",
        "zip_url": "https://alphacephei.com/kaldi/models/vosk-model-small-en-us-0.15.zip",
    }
}

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")
os.makedirs(MODELS_DIR, exist_ok=True)


def ensure_vosk_model(lang_code: str) -> str:
    """Проверяет наличие модели Vosk, скачивает при необходимости."""
    info = VOSK_MODELS[lang_code]
    model_dir = os.path.join(MODELS_DIR, info["name"])

    if os.path.isdir(model_dir) and os.path.exists(os.path.join(model_dir, "am", "final.mdl")):
        return model_dir

    print(f"Загрузка модели Vosk для {lang_code}...")
    url = info["zip_url"]
    zip_path = os.path.join(MODELS_DIR, info["name"] + ".zip")

    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(MODELS_DIR)

        os.remove(zip_path)

        extracted_dirs = [d for d in os.listdir(MODELS_DIR) if d.startswith(info["name"])]
        if extracted_dirs:
            model_dir = os.path.join(MODELS_DIR, extracted_dirs[0])

        print("Модель готова.")
        return model_dir

    except Exception as e:
        raise RuntimeError(f"Ошибка загрузки модели для {lang_code}: {e}")

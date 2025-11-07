import os
from dotenv import load_dotenv
import json

def mock_openrouter_response():
    # Mock a successful JSON response
    return {
        "choices": [
            {
                "message": {
                    "content": '{"bullets": ["Обсудили важные моменты", "Нужно сделать резюме", "Отправить письмо", "Проверить детали", "Подтвердить следующее"], "email_subject": "Резюме встречи", "email_ru": "Уважаемые коллеги, мы обсудили важные моменты встречи. Прошу подтвердить следующее.", "email_en": ""}'
                }
            }
        ]
    }

def test_json_parsing():
    # Test the JSON parsing logic from OpenRouterClient.summarize_and_email
    mock_data = mock_openrouter_response()
    content = mock_data["choices"][0]["message"]["content"]

    print("Testing JSON parsing...")
    try:
        result = json.loads(content)
        print("JSON parsed successfully")
        print(f"Result: {result}")
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        # Fallback
        result = {
            "bullets": [],
            "email_subject": "Резюме встречи",
            "email_ru": content,
            "email_en": ""
        }
        print("Fallback used")

    # Normalize
    bullets = result.get("bullets") or result.get("summary") or []
    subject = result.get("email_subject") or "Резюме встречи"
    email_ru = result.get("email_ru") or ""
    email_en = result.get("email_en") or ""
    print(f"Bullets: {bullets}")
    print(f"Subject: {subject}")
    print(f"Email RU: {email_ru}")
    print(f"Email EN: {email_en}")

def test_invalid_json():
    print("\nTesting invalid JSON response...")
    invalid_content = "This is not JSON, just plain text"
    try:
        result = json.loads(invalid_content)
    except json.JSONDecodeError:
        print("JSON decode error as expected")
        # Fallback
        result = {
            "bullets": [],
            "email_subject": "Резюме встречи",
            "email_ru": invalid_content,
            "email_en": ""
        }
        print("Fallback used")

    bullets = result.get("bullets") or result.get("summary") or []
    subject = result.get("email_subject") or "Резюме встречи"
    email_ru = result.get("email_ru") or ""
    email_en = result.get("email_en") or ""
    print(f"Bullets: {bullets}")
    print(f"Subject: {subject}")
    print(f"Email RU: {email_ru}")
    print(f"Email EN: {email_en}")

def test_empty_response():
    print("\nTesting empty response...")
    empty_content = ""
    try:
        result = json.loads(empty_content)
    except json.JSONDecodeError:
        print("JSON decode error as expected")
        result = {
            "bullets": [],
            "email_subject": "Резюме встречи",
            "email_ru": empty_content,
            "email_en": ""
        }
        print("Fallback used")

    bullets = result.get("bullets") or result.get("summary") or []
    subject = result.get("email_subject") or "Резюме встречи"
    email_ru = result.get("email_ru") or ""
    email_en = result.get("email_en") or ""
    print(f"Bullets: {bullets}")
    print(f"Subject: {subject}")
    print(f"Email RU: {email_ru}")
    print(f"Email EN: {email_en}")

if __name__ == "__main__":
    test_json_parsing()
    test_invalid_json()
    test_empty_response()
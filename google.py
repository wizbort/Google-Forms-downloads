import requests
import re
import json
import os
from bs4 import BeautifulSoup

FORM_URL = "Paste URL"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def get_html(url):
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.text

def extract_fb_json(html):
    marker = "var FB_LOAD_DATA_ ="
    start = html.find(marker)
    if start == -1:
        raise ValueError("❌ Не найден FB_LOAD_DATA_")

    sliced = html[start + len(marker):]
    json_start = sliced.find("[")
    if json_start == -1:
        raise ValueError("❌ Не найден начало JSON массива")
    
    # Ищем конец JSON более точно
    brace_count = 0
    json_end = -1
    for i, char in enumerate(sliced[json_start:], json_start):
        if char == '[':
            brace_count += 1
        elif char == ']':
            brace_count -= 1
            if brace_count == 0:
                json_end = i + 1
                break
    
    if json_end == -1:
        raise ValueError("❌ Не найден конец JSON массива")
    
    json_raw = sliced[json_start:json_end]

    try:
        return json.loads(json_raw)
    except Exception as e:
        print(f"⚠️ Ошибка JSON парсинга: {e}")
        # Попробуем более агрессивную очистку
        import ast
        cleaned = json_raw.replace("null", "None").replace("true", "True").replace("false", "False")
        # Удаляем лишние символы в конце
        while cleaned.endswith(";") or cleaned.endswith("}"):
            cleaned = cleaned[:-1]
        try:
            return ast.literal_eval(cleaned)
        except Exception as e2:
            print(f"⚠️ Ошибка ast.literal_eval: {e2}")
            # Попробуем найти конец JSON более точно
            brace_count = 0
            for i, char in enumerate(json_raw):
                if char == '[':
                    brace_count += 1
                elif char == ']':
                    brace_count -= 1
                    if brace_count == 0:
                        json_raw = json_raw[:i+1]
                        break
            try:
                return json.loads(json_raw)
            except:
                return ast.literal_eval(json_raw.replace("null", "None").replace("true", "True").replace("false", "False"))

def parse_questions(data):
    # Обрабатываем основную секцию данных
    questions_raw = data[0][1][1]
    
    # Также обрабатываем секцию 14, которая содержит правильные ответы
    additional_questions = []
    if len(data) > 14 and isinstance(data[14], list) and len(data[14]) > 1:
        if isinstance(data[14][1], list) and len(data[14][1]) > 1:
            additional_questions = data[14][1][1]
    
    # Объединяем все вопросы
    all_questions = questions_raw + additional_questions
    
    results = []
    
    skipped_headers = 0
    skipped_no_choices = 0
    skipped_invalid_structure = 0
    skipped_no_options = 0
    processed_questions = 0
    skipped_duplicates = 0

    # Словарь для отслеживания уже обработанных вопросов
    processed_questions_dict = {}
    # Словарь для хранения записей с правильными ответами
    correct_answers_dict = {}

    # Сначала собираем все записи с правильными ответами из секции 14
    if len(data) > 14 and isinstance(data[14], list) and len(data[14]) > 1:
        if isinstance(data[14][1], list):
            for i, q in enumerate(data[14][1]):
                if not isinstance(q, list) or len(q) < 5:
                    continue

                q_text = q[1]
                q_choices_root = q[4] if len(q) > 4 else None

                # Проверяем, есть ли правильные ответы в этой записи
                if q_choices_root and isinstance(q_choices_root, list):
                    for choice_block in q_choices_root:
                        if not isinstance(choice_block, list) or len(choice_block) < 9:
                            continue
                        
                        correct_block = choice_block[9] if len(choice_block) > 9 else None
                        if isinstance(correct_block, list) and len(correct_block) > 1:
                            inner_block = correct_block[1]
                            if isinstance(inner_block, list) and len(inner_block) > 0:
                                correct_answers = []
                                for group in inner_block:
                                    if isinstance(group, list):
                                        for item in group:
                                            if isinstance(item, str):
                                                correct_answers.append(item)
                                            elif isinstance(item, list):
                                                correct_answers.extend([str(x) for x in item if x])
                                
                                if correct_answers:
                                    correct_answers_dict[q_text] = correct_answers

    # Теперь обрабатываем все записи
    for i, q in enumerate(all_questions):
        if not isinstance(q, list) or len(q) < 5:
            skipped_invalid_structure += 1
            continue

        q_text = q[1]
        q_type = q[3] if len(q) > 3 else None
        
        # Пропускаем заголовки (тип 8)
        if q_type == 8:
            skipped_headers += 1
            continue
            
        # Если у нас есть правильные ответы для этого вопроса, используем их
        if q_text in correct_answers_dict:
            # Проверяем, есть ли у этого вопроса варианты ответов
            q_choices_root = q[4] if len(q) > 4 else None
            has_options = q_choices_root and isinstance(q_choices_root, list)
            
            if has_options:
                # Если у вопроса есть варианты ответов, обрабатываем их как обычные варианты
                question_processed = False
                for choice_block in q_choices_root:
                    if not isinstance(choice_block, list) or len(choice_block) < 2:
                        continue

                    options = choice_block[1]
                    if not isinstance(options, list):
                        continue

                    correct_answers = correct_answers_dict[q_text]
                    formatted_answers = []
                    for opt in options:
                        if not isinstance(opt, list) or len(opt) == 0:
                            continue
                        answer_text = str(opt[0])
                        if answer_text in correct_answers:
                            formatted_answers.append(f"{answer_text} ✅")
                        else:
                            formatted_answers.append(answer_text)

                    if formatted_answers:
                        results.append((q_text, formatted_answers))
                        processed_questions += 1
                        question_processed = True
                        processed_questions_dict[q_text] = True
                        break
                
                if not question_processed:
                    # Если не удалось обработать как варианты, используем старую логику
                    answers = correct_answers_dict[q_text]
                    if len(answers) > 0:
                        first_answer = answers[0].strip()
                        if first_answer.replace('.', '').replace(',', '').replace('-', '').isdigit() or first_answer.replace('/', '').replace('.', '').replace(',', '').replace('-', '').isdigit():
                            results.append((q_text, [f"{first_answer} ✅"]))
                        else:
                            results.append((q_text, [f"{', '.join(answers)} ✅"]))
                    else:
                        results.append((q_text, [f"{', '.join(answers)} ✅"]))
                    processed_questions += 1
                    processed_questions_dict[q_text] = True
            else:
                # Для вопросов без вариантов ответов используем старую логику
                answers = correct_answers_dict[q_text]
                if len(answers) > 0:
                    first_answer = answers[0].strip()
                    if first_answer.replace('.', '').replace(',', '').replace('-', '').isdigit() or first_answer.replace('/', '').replace('.', '').replace(',', '').replace('-', '').isdigit():
                        results.append((q_text, [f"{first_answer} ✅"]))
                    else:
                        results.append((q_text, [f"{', '.join(answers)} ✅"]))
                else:
                    results.append((q_text, [f"{', '.join(answers)} ✅"]))
                processed_questions += 1
                processed_questions_dict[q_text] = True
            continue
            
        # Если этот вопрос уже был обработан, пропускаем
        if q_text in processed_questions_dict:
            skipped_duplicates += 1
            continue
            
        q_choices_root = q[4] if len(q) > 4 else None
        
        # Обрабатываем вопросы с вариантами ответов
        if q_choices_root and isinstance(q_choices_root, list):
            question_processed = False
            
            # Проверяем, есть ли правильные ответы в структуре
            for choice_block in q_choices_root:
                if not isinstance(choice_block, list) or len(choice_block) < 9:
                    continue
                
                correct_block = choice_block[9] if len(choice_block) > 9 else None
                if isinstance(correct_block, list) and len(correct_block) > 1:
                    correct_answers = []
                    inner_block = correct_block[1]
                    if isinstance(inner_block, list):
                        for group in inner_block:
                            if isinstance(group, list):
                                for item in group:
                                    if isinstance(item, str):
                                        correct_answers.append(item)
                                    elif isinstance(item, list):
                                        correct_answers.extend([str(x) for x in item if x])
                    
                    if correct_answers:
                        # Убираем дублирование для числовых ответов
                        if len(correct_answers) > 0:
                            # Проверяем, является ли первый ответ числом
                            first_answer = correct_answers[0].strip()
                            if first_answer.replace('.', '').replace(',', '').replace('-', '').isdigit() or first_answer.replace('/', '').replace('.', '').replace(',', '').replace('-', '').isdigit():
                                # Для числовых ответов берем только первое значение
                                results.append((q_text, [f"[Правильный ответ: {first_answer}]"]))
                            else:
                                # Для текстовых ответов оставляем все варианты
                                results.append((q_text, [f"[Правильный ответ: {', '.join(correct_answers)}]"]))
                        else:
                            results.append((q_text, [f"[Правильный ответ: {', '.join(correct_answers)}]"]))
                        processed_questions += 1
                        question_processed = True
                        processed_questions_dict[q_text] = True
                        break
            
            # Если не нашли правильные ответы, обрабатываем как обычные варианты
            if not question_processed:
                for choice_block in q_choices_root:
                    if not isinstance(choice_block, list) or len(choice_block) < 2:
                        continue

                    options = choice_block[1]
                    if not isinstance(options, list):
                        continue

                    correct_block = None
                    if len(choice_block) > 9:
                        correct_block = choice_block[9]

                    correct_answers = []
                    if isinstance(correct_block, list) and len(correct_block) > 1:
                        # Более детальная обработка структуры правильных ответов
                        if len(correct_block) > 1:
                            inner_block = correct_block[1]
                            if isinstance(inner_block, list):
                                for group in inner_block:
                                    if isinstance(group, list):
                                        for item in group:
                                            if isinstance(item, str):
                                                correct_answers.append(item)
                                            elif isinstance(item, list):
                                                correct_answers.extend([str(x) for x in item if x])

                    formatted_answers = []
                    for opt in options:
                        if not isinstance(opt, list) or len(opt) == 0:
                            continue
                        answer_text = str(opt[0])
                        if answer_text in correct_answers:
                            formatted_answers.append(f"{answer_text} ✅")
                        else:
                            formatted_answers.append(answer_text)

                    if formatted_answers:
                        results.append((q_text, formatted_answers))
                        processed_questions += 1
                        question_processed = True
                        processed_questions_dict[q_text] = True
                        break  # Обрабатываем только первый блок с вариантами для каждого вопроса
                
                if not question_processed:
                    # Обрабатываем вопросы без вариантов ответов (типы 0, 1 и другие)
                    if q_type == 0:
                        results.append((q_text, ["[Текстовый ответ]"]))
                        processed_questions += 1
                        processed_questions_dict[q_text] = True
                    elif q_type == 1:
                        results.append((q_text, ["[Короткий текстовый ответ]"]))
                        processed_questions += 1
                        processed_questions_dict[q_text] = True
                    else:
                        results.append((q_text, ["[Другой тип ответа]"]))
                        processed_questions += 1
                        processed_questions_dict[q_text] = True
        
        # Обрабатываем вопросы без структуры вариантов
        else:
            if q_type == 0:
                results.append((q_text, ["[Текстовый ответ]"]))
                processed_questions += 1
                processed_questions_dict[q_text] = True
            elif q_type == 1:
                results.append((q_text, ["[Короткий текстовый ответ]"]))
                processed_questions += 1
                processed_questions_dict[q_text] = True
            else:
                skipped_no_choices += 1
                if skipped_no_choices <= 5:
                    print(f"🔍 Пропущен вопрос без вариантов {i}: '{q_text[:50]}...' (тип: {q_type})")
    
    return results

def save_to_txt(data, filename="result_google.txt"):
    with open(filename, "w", encoding="utf-8") as f:
        for i, (q, answers) in enumerate(data, 1):
            f.write("=" * 50 + "\n")
            f.write(f"Вопрос {i}:\n")
            if q is not None:
                f.write(q.strip() + "\n\n")
            else:
                f.write("[Без текста вопроса]\n\n")
            for a in answers:
                f.write(a + "\n")
            f.write("\n")
    
    print(f"✅ Сохранено в {filename}")
    print(f"📊 Всего обработано вопросов: {len(data)}")

def main():
    print("🔍 Загружаем HTML формы...")
    html = get_html(FORM_URL)

    print("📦 Извлекаем JSON...")
    fb_data = extract_fb_json(html)
    
    # Сохраняем сырые данные для анализа
    with open("raw_data.json", "w", encoding="utf-8") as f:
        json.dump(fb_data, f, ensure_ascii=False, indent=2)
    print("💾 Сырые данные сохранены в raw_data.json")

    print("🧠 Ищем вопросы и ответы...")
    parsed = parse_questions(fb_data)

    print("💾 Сохраняем в .txt файл...")
    save_to_txt(parsed)
    
    # Удаляем временный файл с сырыми данными
    if os.path.exists("raw_data.json"):
        os.remove("raw_data.json")
        print("🗑️ Временный файл raw_data.json удален")

if __name__ == "__main__":
    main()

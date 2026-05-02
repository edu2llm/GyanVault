import os
import json
import re
import argparse
from pathlib import Path
from pdf2image import convert_from_path
from PIL import Image

from gyanvault.config import (
    DB_PATH,
    ROOT_OUTPUT_DIR,
    STAGING_DIR,
    FINAL_DIR,
    OCR_DPI,
    MAX_IMAGE_DIMENSION,
    TEXT_CHUNK_SIZE,
)
from gyanvault.db import DBManager
from gyanvault.state import ProcessingState
from gyanvault.ollama_client import OllamaClient
from gyanvault.utils import get_unique_file_id, sanitize_latex_in_json


# =========================================================================
# PHASE 1: DISCOVERY & VISION (The "Eye")
# =========================================================================
def run_pass_1_vision(args):
    print("\n" + "=" * 50)
    print(">>> PASS 1: VISION & TRANSCRIPTION")
    print("=" * 50)

    db = DBManager(str(DB_PATH))
    state = ProcessingState()
    files_processed_count = 0

    cursor = db.conn.cursor()
    where_clauses = []
    params = []

    if args.subject:
        where_clauses.append("LOWER(subject) = ?")
        params.append(args.subject.lower())

    if args.search_term:
        where_clauses.append("(LOWER(path) LIKE ? OR LOWER(pdfs_json) LIKE ?)")
        params.extend([f'%{args.search_term.lower()}%', f'%{args.search_term.lower()}%'])

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    count_query = f"SELECT COUNT(*) FROM downloads WHERE {where_sql}"
    cursor.execute(count_query, params)
    total_records = cursor.fetchone()[0]

    if args.offset >= total_records and total_records > 0:
        print(f"!! Warning: Offset ({args.offset}) is greater than or equal to the total matching records ({total_records}). No files to process in Pass 1.")
        db.close()
        return

    limit_sql = "LIMIT ?"
    params.append(args.max_files if args.max_files > 0 else -1)
    offset_sql = "OFFSET ?"
    params.append(args.offset)

    query = f"SELECT complete_url, year, class, subject, path, pdfs_json FROM downloads WHERE {where_sql} {limit_sql} {offset_sql}"
    cursor.execute(query, params)
    records = cursor.fetchall()

    print(f"DEBUG: Found {len(records)} records in database matching criteria.")

    client = OllamaClient()

    try:
        for row in records:
            target_files = []
            pdfs_json_str = row['pdfs_json']
            main_path = row['path']

            if pdfs_json_str and pdfs_json_str != "[]":
                try:
                    pdf_list = json.loads(pdfs_json_str)
                    target_files = [p['file'] for p in pdf_list]
                except json.JSONDecodeError:
                    target_files = []

            if not target_files and main_path and main_path.lower().endswith('.pdf'):
                if str(main_path).startswith("output/"):
                    target_files = [str(main_path).replace("output/", "", 1)]
                else:
                    target_files = [main_path]
            if not target_files:
                continue

            for rel_path in target_files:
                file_id = get_unique_file_id(rel_path)
                full_pdf_path = os.path.join(ROOT_OUTPUT_DIR, rel_path)
                raw_text_path = os.path.join(STAGING_DIR, f"{file_id}_raw.txt")

                if not os.path.exists(full_pdf_path):
                    full_pdf_path_alt = os.path.join(ROOT_OUTPUT_DIR, "output", rel_path)
                    if os.path.exists(full_pdf_path_alt):
                        full_pdf_path = full_pdf_path_alt
                    else:
                        print(f"   !! File not found: {rel_path}")
                        continue

                if args.max_files > 0 and files_processed_count >= args.max_files:
                    print(f"-> Reached file consideration limit ({args.max_files}). Stopping Pass 1.")
                    return

                if os.path.exists(raw_text_path):
                    pdf_mtime = os.path.getmtime(full_pdf_path)
                    raw_text_mtime = os.path.getmtime(raw_text_path)
                    if pdf_mtime < raw_text_mtime:
                        print(f"-> Skipping (raw text is up-to-date): {rel_path}")
                        files_processed_count += 1
                        continue
                    else:
                        print(f"-> Re-processing (source PDF has been updated): {rel_path}")
                print(f"-> Processing: {rel_path}")

                try:
                    images = convert_from_path(full_pdf_path, dpi=OCR_DPI)
                except Exception as e:
                    print(f"   !! PDF Conversion Error for {rel_path}: {e}")
                    continue
                full_text_content = ""

                for i, image in enumerate(images):
                    if max(image.size) > MAX_IMAGE_DIMENSION:
                        image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)

                    temp_img_path = os.path.join(STAGING_DIR, "temp_vision.png")
                    image.save(temp_img_path)

                    prompt = (
                        "Transcribe this page line-by-line. IMPORTANT: Only transcribe the English text. "
                        "Ignore all Hindi text entirely.\n"
                        "1. If you see a diagram, graph, or geometric figure, describe it in detail "
                        "inside square brackets like this: [DIAGRAM: A triangle with sides 5cm...].\n"
                        "2. If you see math formulas, write them in LaTeX format.\n"
                        "3. Do not add any extra commentary, only the transcription."
                    )

                    page_text = client.generate_with_image(
                        image_path=Path(temp_img_path),
                        prompt=prompt,
                        max_tokens=1024,
                        temperature=0.2,
                    )

                    full_text_content += f"\n--- PAGE {i+1} ---\n{page_text}\n"

                with open(raw_text_path, "w", encoding="utf-8") as f:
                    f.write(full_text_content)

                subject = row['subject']
                if subject and subject.lower() == 'download':
                    stem = Path(rel_path).stem
                    guessed_subject = re.sub(r'^[0-9\s\(\)A-Z_-]+', '', stem, flags=re.IGNORECASE).strip()
                    if guessed_subject:
                        subject = guessed_subject

                meta = {
                    "subject": subject,
                    "class": row['class'],
                    "year": row['year'],
                    "original_path": rel_path,
                }
                with open(os.path.join(STAGING_DIR, f"{file_id}_meta.json"), "w", encoding="utf-8") as f:
                    json.dump(meta, f)

                print(f"   [Saved] {file_id}_raw.txt")
                state.pass1_completed.add(file_id)
                files_processed_count += 1

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected. Saving state and exiting Pass 1 gracefully.")
    except Exception as e:
        print(f"\nAn unexpected error occurred in Pass 1: {e}")
    finally:
        state.save()


# =========================================================================
# PHASE 2: LOGIC & JSON FORMATTING (The "Brain")
# =========================================================================
def run_pass_2_logic(args):
    print("\n" + "=" * 50)
    print(">>> PASS 2: LOGIC & JSON FORMATTING")
    print("=" * 50)

    state = ProcessingState()
    files_processed_count = 0
    client = OllamaClient()

    pending_files_for_pass2 = []
    for f in os.listdir(STAGING_DIR):
        if f.endswith("_raw.txt"):
            file_id = f.split("_")[0]
            meta_path = os.path.join(STAGING_DIR, f"{file_id}_meta.json")
            if os.path.exists(meta_path):
                with open(meta_path, 'r') as mf:
                    meta = json.load(mf)

                if file_id not in state.pass1_completed:
                    continue

                if file_id in state.pass2_completed:
                    print(f"-> Skipping (Pass 2 completed): {file_id}")
                    continue

                final_path_check = os.path.join(FINAL_DIR, f"{file_id}_{meta.get('subject', 'unknown')}.json")
                if os.path.exists(final_path_check):
                    print(f"-> Skipping (final JSON already exists): {file_id}")
                    continue
                pending_files_for_pass2.append((f, meta, file_id))

    if not pending_files_for_pass2:
        print(">>> No pending files for Pass 2.")
        return

    try:
        for filename, meta, file_id in pending_files_for_pass2:
            if args.max_files > 0 and files_processed_count >= args.max_files:
                print(f"-> Reached maximum number of files to process ({args.max_files}). Stopping Pass 2.")
                return

            print(f"-> Structuring JSON for {meta.get('subject')} (File ID: {file_id})")

            with open(os.path.join(STAGING_DIR, filename), "r", encoding="utf-8") as f:
                raw_text = f.read()

            text_chunks = []
            current_chunk = ""
            for line in raw_text.split('\n'):
                if len(current_chunk) > TEXT_CHUNK_SIZE and ('---' in line or re.match(r'^\d+\.', line)):
                    text_chunks.append(current_chunk)
                    current_chunk = line + "\n"
                else:
                    current_chunk += line + "\n"
            if current_chunk:
                text_chunks.append(current_chunk)

            all_questions = []
            chunk_metadata = None

            for chunk_idx, chunk_text in enumerate(text_chunks):
                print(f"   Processing chunk {chunk_idx + 1}/{len(text_chunks)}...")

                system_prompt = (
                    "You are a CBSE Question Paper digitization expert and JSON generation expert. "
                    "Output ONLY valid, properly escaped JSON."
                )

                user_prompt = rf"""You are a CBSE Question Paper digitization expert.

CONTEXT:
Subject: {meta['subject']}
Class: {meta['class']}
Year: {meta['year']}
Source File: {meta.get('original_path', 'N/A')}
Chunk: {chunk_idx + 1}/{len(text_chunks)}

TASK:
Convert the OCR text into clean JSON. Output ONLY valid JSON, no markdown, no explanations.

CRITICAL RULES FOR JSON OUTPUT:
1. Every JSON string must be enclosed in double quotes "..."
2. Every backslash inside a string MUST be escaped. For example:
   - LaTeX command \sin must be written as "\\sin" in JSON
   - LaTeX command \frac must be written as "\\frac" in JSON
   - Backslashes in math: "x = \\sqrt{{a + b}}"
3. Double quotes inside strings must be escaped: \"
4. Extract ONLY English questions. Ignore Hindi entirely.
5. If a question is incomplete or cut off, DO NOT include it.
6. For MCQ, capture options (A), (B), (C), (D) in an options object.
7. Include diagram descriptions in [DIAGRAM: ...] or set to "N/A".

EXAMPLE OF CORRECT JSON OUTPUT:
{{
    "metadata": {{"subject": "Mathematics", "year": "{meta['year']}", "refined_subject": ""}},
    "questions": [
        {{
            "q_no": "1",
            "text": "Find the domain of \\\\sin^{{-1}}(2x - 1).",
            "options": {{
                "A": "[0, 1]",
                "B": "[0.5, 1]",
                "C": "[-1, 1]"
            }},
            "marks": "2",
            "answer": "Using \\\\sin^{{-1}}(u) requires -1 <= u <= 1. So -1 <= 2x - 1 <= 1 means 0 <= x <= 1. Answer: [0, 1]"
        }}
    ]
}}

RAW OCR TEXT:
{chunk_text[:2500]}

OUTPUT ONLY THE JSON (no markdown, no code blocks, no explanations):
"""

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]

                json_str = client.chat(
                    messages=messages,
                    fmt="json",
                    max_tokens=4000,
                    temperature=0.2,
                )

                final_name = f"{file_id}_{meta.get('subject', 'unknown')}.json"
                final_path = os.path.join(FINAL_DIR, final_name)

                try:
                    start_index = json_str.find('{')
                    end_index = json_str.rfind('}')

                    if start_index == -1 or end_index == -1 or end_index <= start_index:
                        print(f"   [Warn] No valid JSON in chunk {chunk_idx + 1}. Skipping.")
                        continue

                    clean_json = json_str[start_index : end_index + 1]
                    clean_json = sanitize_latex_in_json(clean_json)
                    clean_json = re.sub(r",\s*([}\]])", r"\1", clean_json)

                    parsed_json = json.loads(clean_json)

                    if "questions" in parsed_json:
                        validated_questions = []
                        for q in parsed_json["questions"]:
                            if all(k in q for k in ["q_no", "text", "marks"]):
                                if q["text"].strip().endswith((":", "?", ".")):
                                    validated_questions.append(q)
                                else:
                                    print(f"   [Warn] Skipping incomplete Q{q.get('q_no', '?')}")
                        all_questions.extend(validated_questions)

                    if "metadata" in parsed_json:
                        chunk_metadata = parsed_json["metadata"]

                except json.JSONDecodeError as e:
                    print(f"   [Warn] JSON parse error in chunk {chunk_idx + 1}: {e}")
                    with open(final_path + f".err.chunk{chunk_idx}", "w", encoding="utf-8") as f:
                        f.write(json_str)
                except Exception as e:
                    print(f"   [Warn] Error processing chunk {chunk_idx + 1}: {e}")

            if all_questions:
                final_output = {
                    "metadata": chunk_metadata or {
                        "subject": meta['subject'],
                        "year": meta['year'],
                        "refined_subject": meta.get('subject', ''),
                    },
                    "questions": all_questions,
                }

                with open(final_path, "w", encoding="utf-8") as f:
                    json.dump(final_output, f, indent=2, ensure_ascii=False)

                print(f"   [Success] Saved {final_name} with {len(all_questions)} questions")
                state.pass2_completed.add(file_id)
                files_processed_count += 1
            else:
                print(f"   [Fail] No valid questions extracted for {file_id}")

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected. Saving state and exiting Pass 2 gracefully.")
    except Exception as e:
        print(f"\nAn unexpected error occurred in Pass 2: {e}")
    finally:
        state.save()


def query_and_print(args):
    print("\n" + "=" * 50)
    print(">>> QUERY-ONLY MODE")
    print("=" * 50)
    db = DBManager(str(DB_PATH))
    cursor = db.conn.cursor()

    where_clauses = []
    params = []

    if args.subject:
        where_clauses.append("LOWER(subject) = ?")
        params.append(args.subject.lower())

    if args.search_term:
        where_clauses.append("(LOWER(path) LIKE ? OR LOWER(pdfs_json) LIKE ?)")
        params.extend([f'%{args.search_term.lower()}%', f'%{args.search_term.lower()}%'])

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    count_query = f"SELECT COUNT(*) FROM downloads WHERE {where_sql}"
    cursor.execute(count_query, params)
    total_records = cursor.fetchone()[0]

    if args.offset >= total_records:
        print(f"!! Warning: Offset ({args.offset}) is greater than or equal to the total matching records ({total_records}). No files to process.")
        db.close()
        return

    limit_sql = "LIMIT ?"
    params.append(args.max_files if args.max_files > 0 else -1)
    offset_sql = "OFFSET ?"
    params.append(args.offset)

    query = f"SELECT complete_url, year, class, subject, path, pdfs_json FROM downloads WHERE {where_sql} {limit_sql} {offset_sql}"
    cursor.execute(query, params)
    records = cursor.fetchall()

    print(f"Found {len(records)} matching records (total: {total_records}):")
    for row in records:
        print(f"  - {row['path']} | {row['subject']} | {row['year']} | {row['class']}")

    db.close()


def main():
    parser = argparse.ArgumentParser(description="Digitize PDF documents in two passes.")
    parser.add_argument('--max_files', type=int, default=-1,
                        help="Maximum number of unique PDF files to process in each pass. "
                             "Set to -1 for no limit. Default: -1.")
    parser.add_argument('--offset', type=int, default=0,
                        help="Number of records to skip in the database query. Default: 0.")
    parser.add_argument('--subject', type=str, default=None,
                        help="Filter records by a specific subject (case-insensitive).")
    parser.add_argument('--search_term', type=str, default='mathematics',
                        help="An arbitrary term to search for in the 'path' or 'pdfs_json' fields. "
                             "Default: 'mathematics'.")
    parser.add_argument('--query_only', action='store_true',
                        help="If set, the script will only query the database with the given filters, "
                             "print the matching files, and then exit without processing.")
    args = parser.parse_args()

    if args.query_only:
        query_and_print(args)
        return

    print(f"Starting digitization process with the following settings:")
    print(f"  - Subject: {args.subject or 'Any'}")
    print(f"  - Search Term: '{args.search_term}'")
    print(f"  - Max Files: {args.max_files if args.max_files > 0 else 'No Limit'}")
    print(f"  - Offset: {args.offset}")

    # Uncomment to run Pass 1 (Vision/OCR)
    # run_pass_1_vision(args)
    run_pass_2_logic(args)


if __name__ == "__main__":
    main()

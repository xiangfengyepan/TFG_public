import os
import re
import csv

INPUT_FILE_FOLDER = "agents_csv"
OUTPUT_FILE = "prompt_analysis.csv"

import re

import re

def extract_features(text):
    # Regex patterns
    rx_use_of_words = re.compile(r"\b(should|must|have to)\b", re.IGNORECASE)
    rx_punctuation = re.compile(r"[!?]")
    rx_uppercase = re.compile(r"\b[A-Z]+\b")

    # Split text into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)

    # Containers for each category
    uppercase_sentences = []
    use_of_words_sentences = []
    punctuation_sentences = []

    for sentence in sentences:
        if rx_uppercase.search(sentence):
            uppercase_sentences.append(sentence.strip())
        if rx_use_of_words.search(sentence):
            use_of_words_sentences.append(sentence.strip())
        if rx_punctuation.search(sentence):
            punctuation_sentences.append(sentence.strip())

    # Return as tuple, sentences joined by "|"
    return (
        " | ".join(uppercase_sentences),
        " | ".join(use_of_words_sentences),
        " | ".join(punctuation_sentences)
    )

def main():
    # Regex patterns
    rx_prompt_col = re.compile(r"^Prompt \d$")

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as out_file:
        writer = csv.writer(out_file)
        writer.writerow([
            "Repo",
            "Agent",
            "UPPERCASE",
            "Use of words",
            "Punctuation",
            "Comments"
        ])

        for filename in os.listdir(INPUT_FILE_FOLDER):
            if not filename.endswith(".csv"):
                continue

            repo_name = filename
            file_path = os.path.join(INPUT_FILE_FOLDER, filename)

            with open(file_path, newline="", encoding="utf-8") as r_file:
                reader = csv.DictReader(r_file)

                prompt_columns = [
                    col for col in reader.fieldnames
                    if rx_prompt_col.search(col)
                ]

                for row in reader:
                    agent = row.get("Name", "UNKNOWN")

                    for col in prompt_columns:
                        text = row.get(col, "")
                        if not text:
                            continue

                        uppercase, use_of_words, punctuation = extract_features(text)

                        writer.writerow([
                            repo_name,
                            agent,
                            uppercase,
                            use_of_words,
                            punctuation,
                            ""
                        ])
    print("Done!")

if __name__ == "__main__":
    main()
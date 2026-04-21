import os
import re
import csv

INPUT_FILE_FOLDER = "agents_csv"
OUTPUT_FILE = "prompt_analysis.csv"


def extract_features(text):
    """
    Extract prompt-engineering pattern features from a prompt string.

    Returns a tuple of eight strings, one per pattern category.  Each string
    contains the matching sentences joined by " | ", or an empty string when
    no match is found.

    Patterns
    --------
    1. UPPERCASE      – sentences that contain a fully-uppercase word (length >= 2),
                        e.g. IMPORTANT, MUST, NOTE, WARNING.
    2. Use of words   – sentences with directive modal/obligatory verbs:
                        should / must / have to / need to / always / ensure.
    3. Punctuation    – sentences ending with ! or containing ?.
    4. Markup tags    – sentences containing an XML/HTML-style tag, e.g. <IMPORTANT>,
                        </instruction>, [INST].
    5. Role def.      – sentences that open with "You are (a|an|the|an AI|…)" or
                        "Act as", establishing the agent's persona.
    6. Negation       – sentences with explicit prohibitions:
                        do not / don't / never / avoid / must not / cannot / refrain.
    7. Output format  – sentences that specify the expected response structure:
                        return / output / format / JSON / markdown / YAML / XML /
                        structured / bullet / numbered / list.
    8. Numbered list  – lines that begin with a number followed by . or ),
                        indicating an enumerated instruction list.
    """

    # ---- Compiled regexes ----
    rx_uppercase   = re.compile(r"\b[A-Z]{2,}\b")
    rx_use_words   = re.compile(
        r"\b(should|must|have to|need to|always|ensure)\b", re.IGNORECASE
    )
    rx_punctuation = re.compile(r"[!?]")
    rx_markup      = re.compile(r"</?[A-Za-z_][A-Za-z0-9_/]*>|\[[A-Z]+\]")
    rx_role        = re.compile(
        r"\b(You are (a|an|the|an AI|a helpful|a software|an expert|an experienced)|Act as)\b",
        re.IGNORECASE,
    )
    rx_negation    = re.compile(
        r"\b(do not|don't|never|avoid|must not|cannot|can't|refrain|do NOT)\b",
        re.IGNORECASE,
    )
    rx_output_fmt  = re.compile(
        r"\b(return|output|format|JSON|markdown|YAML|XML|structured|bullet|numbered list"
        r"|in the form|as a list|response must|your response)\b",
        re.IGNORECASE,
    )
    rx_numbered    = re.compile(r"^\s*\d+[\.\)]\s+\S.{5,}", re.MULTILINE)

    # ---- Split into sentences / lines ----
    sentences = re.split(r"(?<=[.!?])\s+|\n", text)

    buckets = {
        "uppercase":    [],
        "use_words":    [],
        "punctuation":  [],
        "markup":       [],
        "role":         [],
        "negation":     [],
        "output_fmt":   [],
        "numbered":     [],
    }

    for sentence in sentences:
        s = sentence.strip()
        if not s:
            continue
        if rx_uppercase.search(s):
            buckets["uppercase"].append(s)
        if rx_use_words.search(s):
            buckets["use_words"].append(s)
        if rx_punctuation.search(s):
            buckets["punctuation"].append(s)
        if rx_markup.search(s):
            buckets["markup"].append(s)
        if rx_role.search(s):
            buckets["role"].append(s)
        if rx_negation.search(s):
            buckets["negation"].append(s)
        if rx_output_fmt.search(s):
            buckets["output_fmt"].append(s)
        # (handled below on raw text)

    # Numbered list: scan raw text with MULTILINE (splitter destroys these lines)
    buckets["numbered"] = rx_numbered.findall(text)

    sep = "\n"
    return (
        sep.join(buckets["uppercase"]),
        sep.join(buckets["use_words"]),
        sep.join(buckets["punctuation"]),
        sep.join(buckets["markup"]),
        sep.join(buckets["role"]),
        sep.join(buckets["negation"]),
        sep.join(buckets["output_fmt"]),
        sep.join(buckets["numbered"]),
    )


def main():
    rx_prompt_col = re.compile(r"^Prompt \d$")

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as out_file:
        writer = csv.writer(out_file)
        writer.writerow([
            "Repo",
            "Agent",
            "UPPERCASE",
            "Use of words",
            "Punctuation",
            "Markup tags",
            "Role definition",
            "Negation",
            "Output format",
            "Numbered list",
            "Comments",
        ])

        for filename in sorted(os.listdir(INPUT_FILE_FOLDER)):
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

                        (uppercase, use_words, punctuation,
                         markup, role, negation, output_fmt, numbered) = extract_features(text)

                        writer.writerow([
                            repo_name,
                            agent,
                            uppercase,
                            use_words,
                            punctuation,
                            markup,
                            role,
                            negation,
                            output_fmt,
                            numbered,
                            "",
                        ])

    print("Done! Output written to", OUTPUT_FILE)


if __name__ == "__main__":
    main()

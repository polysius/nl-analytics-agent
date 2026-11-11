"""Run every gold query and print its result, so a person can check each answer by eye."""

from nlagent.benchmark import load_questions
from nlagent.db import run_query

if __name__ == "__main__":
    for question in load_questions():
        result = run_query(question.gold_sql)
        preview = result.rows[:4]
        print(f"{question.id} [{question.difficulty}] {question.question}")
        print(f"    rows={len(result.rows)} {preview}")

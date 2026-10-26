"""School Learning assessment engine (no Streamlit): ten question types, one checker, explanations for every answer.

Every question is data (a dict in a lesson file). check() returns a Result with whether the answer is correct, an
explanation for the choice the student made, and whether it was auto-marked. Written answers are never auto-marked:
the student compares their answer with a model answer and a checklist (self-check), which is not counted as a score.

Types
    mcq        q, options [{text, why}], answer (index)            one correct option; "why" explains each option
    truefalse  statement, answer (bool), explain
    fill       text with "___", answers [accepted], explain        short factual answers, compared after normalising
    match      q, pairs [[left, right], …], explain                every left matched to its right (select boxes)
    order      q, items [in the correct order], explain            chronological ordering (move up / move down)
    map        mcq + figure (an SVG with numbered markers) + marker
    image      mcq + figure (an original illustration) + alt
    scenario   situation, options [{text, verdict, why}], explain  verdict: best | acceptable | poor; best is correct
    short      prompt, model, points [checklist]                    self-check only, never auto-marked
"""
from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass

TYPES = ("mcq", "truefalse", "fill", "match", "order", "map", "image", "scenario", "short")
CHOICE_TYPES = ("mcq", "map", "image")
VERDICTS = ("best", "acceptable", "poor")


class QuestionError(ValueError):
    pass


@dataclass(frozen=True)
class Result:
    correct: bool | None        # None: not auto-marked (written answer)
    explanation: str
    detail: tuple = ()          # per-part feedback (match / order)
    marked: bool = True


def normalise(text) -> str:
    """Case, accents, punctuation and spacing do not matter for short factual answers."""
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    s = re.sub(r"\b(the|a|an)\b", " ", s)
    return " ".join(s.split())


def validate(q: dict, figures: set[str] | None = None) -> None:
    """Fail loudly on a malformed question (the content tests run this for every question)."""
    qid, kind = q.get("id"), q.get("type")
    if not qid or not re.fullmatch(r"[a-z0-9-]{2,40}", str(qid)):
        raise QuestionError(f"bad question id {qid!r}")
    if kind not in TYPES:
        raise QuestionError(f"{qid}: unknown type {kind!r}")
    if kind in CHOICE_TYPES:
        opts = q.get("options") or []
        if not q.get("q") or len(opts) < 2 or not 0 <= int(q.get("answer", -1)) < len(opts):
            raise QuestionError(f"{qid}: needs q, at least two options and a valid answer")
        if len({o["text"] for o in opts}) != len(opts) or not all(o.get("why") for o in opts):
            raise QuestionError(f"{qid}: options must be different and each needs a 'why' explanation")
        if kind in ("map", "image") and (not q.get("figure") or (figures is not None and q["figure"] not in figures)):
            raise QuestionError(f"{qid}: {kind} questions need an existing figure")
        if kind == "image" and not q.get("alt"):
            raise QuestionError(f"{qid}: image questions need alt text")
    elif kind == "truefalse":
        if not q.get("statement") or not isinstance(q.get("answer"), bool) or not q.get("explain"):
            raise QuestionError(f"{qid}: needs statement, a true/false answer and explain")
    elif kind == "fill":
        if "___" not in str(q.get("text", "")) or not q.get("answers") or not q.get("explain"):
            raise QuestionError(f"{qid}: needs text with ___, accepted answers and explain")
    elif kind == "match":
        pairs = q.get("pairs") or []
        if len(pairs) < 3 or len({p[0] for p in pairs}) != len(pairs) or len({p[1] for p in pairs}) != len(pairs):
            raise QuestionError(f"{qid}: needs at least three pairs with distinct sides")
        if not q.get("q") or not q.get("explain"):
            raise QuestionError(f"{qid}: needs q and explain")
    elif kind == "order":
        items = q.get("items") or []
        if len(items) < 3 or len(set(items)) != len(items) or not q.get("q") or not q.get("explain"):
            raise QuestionError(f"{qid}: needs q, at least three distinct items and explain")
    elif kind == "scenario":
        opts = q.get("options") or []
        if not q.get("situation") or len(opts) < 2 or sum(1 for o in opts if o.get("verdict") == "best") != 1:
            raise QuestionError(f"{qid}: needs a situation and exactly one best option")
        if not all(o.get("verdict") in VERDICTS and o.get("why") for o in opts) or not q.get("explain"):
            raise QuestionError(f"{qid}: every option needs a verdict and why; the question needs explain")
    elif kind == "short":
        if not q.get("prompt") or not q.get("model") or len(q.get("points") or []) < 2:
            raise QuestionError(f"{qid}: needs prompt, model answer and at least two checklist points")


def check(q: dict, response) -> Result:
    """Mark one response. Choice types: the chosen option index. truefalse: bool. fill: text. match: {left: right}.
    order: list of items in the student's order. scenario: option index. short: text (never auto-marked)."""
    kind = q["type"]
    if kind in CHOICE_TYPES:
        i = int(response)
        right = i == int(q["answer"])
        why = q["options"][i]["why"]
        if not right:
            why += " " + "Correct answer: " + q["options"][q["answer"]]["text"] + ". " + q["options"][q["answer"]]["why"]
        return Result(right, why)
    if kind == "truefalse":
        right = bool(response) is q["answer"]
        return Result(right, ("Correct. " if right else f"Not quite: the statement is {'true' if q['answer'] else 'false'}. ")
                      + q["explain"])
    if kind == "fill":
        right = normalise(response) in {normalise(a) for a in q["answers"]}
        return Result(right, ("Correct. " if right else f"The expected answer is “{q['answers'][0]}”. ") + q["explain"])
    if kind == "match":
        given = dict(response or {})
        detail = tuple((left, given.get(left), right, given.get(left) == right) for left, right in q["pairs"])
        right = all(ok for *_, ok in detail)
        return Result(right, q["explain"], detail)
    if kind == "order":
        given = list(response or [])
        detail = tuple((i + 1, item, given[i] if i < len(given) else None, i < len(given) and given[i] == item)
                       for i, item in enumerate(q["items"]))
        right = given == list(q["items"])
        return Result(right, q["explain"], detail)
    if kind == "scenario":
        opt = q["options"][int(response)]
        best = next(o for o in q["options"] if o["verdict"] == "best")
        text = opt["why"] + ("" if opt is best else " The best response: " + best["text"] + ".") + " " + q["explain"]
        return Result(opt["verdict"] == "best", text)
    if kind == "short":
        return Result(None, "Compare your answer with the model answer and the checklist below. Written answers are "
                            "not marked automatically.", marked=False)
    raise QuestionError(kind)


def shuffled_order(q: dict, seed=None) -> list[str]:
    """A starting order for an ordering question that is never already correct."""
    items = list(q["items"])
    rnd = random.Random(seed)
    for _ in range(20):
        rnd.shuffle(items)
        if items != list(q["items"]):
            return items
    return list(reversed(q["items"]))


def match_options(q: dict, seed=None) -> list[str]:
    rights = [p[1] for p in q["pairs"]]
    random.Random(seed).shuffle(rights)
    return rights


# --------------------------------------------------------------------------- a knowledge-check session

def new_session(lesson_id: str, questions: list[dict], seed=None) -> dict:
    """All of a lesson's assessment questions, in the lesson's order (choice options keep their order: each option has
    its own explanation, so the order is part of the teaching)."""
    return {"lesson": lesson_id, "items": [q["id"] for q in questions], "index": 0, "answers": [], "finished": False,
            "seed": seed if seed is not None else random.randrange(10**6)}


def answer(session: dict, q: dict, index: int, response) -> Result | None:
    """Record an answer once (a double click or rerun cannot answer twice)."""
    if session["finished"] or index != session["index"] or len(session["answers"]) != index:
        return None
    if session["items"][index] != q["id"]:
        return None
    result = check(q, response)
    session["answers"].append({"id": q["id"], "correct": result.correct, "marked": result.marked})
    return result


def advance(session: dict, index: int) -> bool:
    if index != session["index"] or len(session["answers"]) != index + 1:
        return False
    if index + 1 >= len(session["items"]):
        session["finished"] = True
    else:
        session["index"] = index + 1
    return True


def tally(session: dict) -> dict:
    """Marked questions only; written answers are counted separately as self-checked."""
    marked = [a for a in session["answers"] if a["marked"]]
    right = sum(1 for a in marked if a["correct"])
    return {"marked": len(marked), "correct": right, "written": len(session["answers"]) - len(marked),
            "percent": round(100 * right / len(marked)) if marked else None}


def score_out_of(session: dict, total: int = 10) -> int:
    """The marked score scaled to the School Learning progress scale (out of 10)."""
    t = tally(session)
    return round(total * t["correct"] / t["marked"]) if t["marked"] else 0

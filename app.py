from flask import Flask, render_template, request
import google.generativeai as genai
import re
import os
from dotenv import load_dotenv
import mysql.connector
import requests 

load_dotenv()

app = Flask(__name__)

#  Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key="GEMINI_API_KEY")
gemini_model = genai.GenerativeModel("gemini-2.5-flash")

#  NewsAPI
NEWSAPI_KEY = os.getenv("NEWS_API_KEY")
NEWSAPI_KEY = "NEWS_API_KEY" 

def newsapi_check(query):
    """
    Check recent news using NewsAPI.
    If a similar headline is found in live news → Real
    Else → Unknown (Gemini decide karega)
    """
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "language": "en",
            "pageSize": 5,
            "apiKey": NEWSAPI_KEY
        }
        resp = requests.get(url, params=params, timeout=5)
        data = resp.json()

        if data.get("totalResults", 0) == 0 or "articles" not in data:
            return "Unknown"

        q = query.lower()

        q_words = [w for w in re.findall(r"\w+", q) if len(w) > 3]

        for article in data["articles"]:
            title = (article.get("title") or "").lower()
            if not title:
                continue
            
            common = sum(1 for w in q_words if w in title)
            if q_words and common >= max(1, len(q_words) // 2):
                return "Real"

        return "Unknown"
    except Exception as e:
        print("NewsAPI error:", e)
        return "Unknown"


#  MySQL
db = mysql.connector.connect(
    host="127.0.0.1",
    user="root",
    password="mysql_123987_45610",
    database="newsify_db"
)
cursor = db.cursor()


def gemini_fact_check(user_input):

    prompt = f"""
You are an expert real-time fact-checking AI system named 'Newsify Verifier' in 2025. 
Your task is to verify the accuracy of the following news headline or statement using 
your up-to-date knowledge base, cross-referencing with trusted and verifiable sources 
such as BBC, Reuters, The Hindu, NDTV, Wikipedia, Aaj Tak, ABP News and official government portals in recent sources, and always refer latest soures over the older one and respond correspondingly.

If the statement refers to an event that already happened, confirm it as Real.
If the statement refers to a future or incorrect/unverified event, classify it as Fake.
If the information is unclear or unverifiable, classify it as Uncertain.

Strictly respond in this exact structured format:


Verdict: Real / Fake / Uncertain
Reason: <one-sentence logical reason based on factual context>
Confidence: High / Medium / Low
Details: <brief paragraph (20–50 words) summarizing evidence or facts supporting your verdict>
Sources: <comma-separated list of 1–3 most reliable real-world sources or websites>

Now, fact-check this statement carefully:

Statement: "{user_input}"

End your response after 'Sources'.
"""

    try:
        response = gemini_model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error: {e}"


def parse_gemini_output(text):
    out = {
        "verdict": "Uncertain",
        "reason": "No short reason provided.",
        "confidence": "Low",
        "details": "",
        "sources": "None"
    }

    if not text:
        return out

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        if ln.lower().startswith("verdict:"):
            out["verdict"] = ln.split(":", 1)[1].strip()
        elif ln.lower().startswith("reason:"):
            out["reason"] = ln.split(":", 1)[1].strip()
        elif ln.lower().startswith("confidence:"):
            out["confidence"] = ln.split(":", 1)[1].strip()
        elif ln.lower().startswith("details:"):
            out["details"] = ln.split(":", 1)[1].strip()
        elif ln.lower().startswith("sources:"):
            out["sources"] = ln.split(":", 1)[1].strip()

    if out["details"] == "" and len(lines) >= 3:
        out["details"] = max(lines, key=len)

    return out


@app.route("/", methods=["GET", "POST"])
def index():

    if request.method == "POST":
        headline = request.form["headline"].strip()

        # 1) News_API check
        api_verdict = newsapi_check(headline)   # Real / Unknown

        # 2) Gemini_API check
        raw = gemini_fact_check(headline)
        parsed = parse_gemini_output(raw)

        # 3) Hybrid decision logic
        verdict_text = parsed["verdict"].lower()

        if api_verdict == "Real":
            final = "Real News"
        elif "real" in verdict_text:
            final = "Real News"
        elif "fake" in verdict_text:
            final = "Fake News"
        else:
            final = "Uncertain"

        # Save into DB
        query = """INSERT INTO results (headline, verdict, reason, confidence, details, sources)
                   VALUES (%s, %s, %s, %s, %s, %s)"""
        values = (
            headline,
            final,
            parsed["reason"],
            parsed["confidence"],
            parsed["details"],
            parsed["sources"]
        )
        cursor.execute(query, values)
        db.commit()

        return render_template(
            "result.html",
            headline=headline,
            final=final,
            reason=parsed["reason"],
            confidence=parsed["confidence"],
            details=parsed["details"],
            sources=parsed["sources"]
        )

    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)

import streamlit as st
from openai import OpenAI

# ----------------------------
# Page setup
# ----------------------------
st.set_page_config(page_title="Northpaw", page_icon="🐻🧭", layout="centered")
st.title("🐻🧭 Northpaw (Capstone Prototype)")
st.caption(
    "A context-aware donation decision assistant. Not medical/legal advice. "
    "Always confirm current guidelines with an organization."
)

# ----------------------------
# Core rules (reliability layer)
# ----------------------------
DO_NOT_DONATE = {
    "Clothing": ["Stained/torn items", "Used underwear/socks", "Single shoes", "Items with strong odors/mold"],
    "Hygiene items": ["Opened toiletries", "Partially used cosmetics", "Unsealed liquids likely to leak"],
    "Food (shelf-stable)": ["Expired food", "Opened packages", "Homemade canned goods (unless explicitly accepted)"],
    "Baby/kids items": ["Used car seats (often not accepted)", "Items missing safety labels/parts"],
    "School supplies": ["Used notebooks with writing", "Broken pens/markers"],
    "Disaster relief": ["Random used clothing (unless requested)", "Unsorted donations", "Items not requested by responders"],
}

PACKING_TIPS = [
    "Sort by type and size, and label bags/boxes clearly.",
    "Keep sets together (e.g., pairs, matching lids).",
    "Call or check the org’s site to confirm they accept the item category.",
]

# ----------------------------
# Hybrid allocation engine (structured layer)
# ----------------------------
PATHWAYS = [
    "Donate money",
    "Donate goods locally",
    "Donate goods to a better-fit region",
    "Volunteer / give time locally",
]

def score_pathways(location: str, month: str, category: str, intent: str, extra: str) -> tuple[list[dict], list[str], list[str]]:
    """
    Returns: (ranked_pathways, flags, assumptions)
    Each pathway dict: {name, score, reasons}
    """
    text = f"{intent or ''} {extra or ''}".lower()

    # Light heuristics (simple on purpose)
    mentions_pickup = any(k in text for k in ["pickup", "pick up", "collect", "haul", "truck"])
    mentions_shipping = any(k in text for k in ["ship", "shipping", "mail", "overseas", "international"])
    mentions_time = any(k in text for k in ["volunteer", "volunteering", "time", "weekend", "help in person"])
    urgent = any(k in text for k in ["urgent", "asap", "immediately", "emergency", "disaster", "flood", "earthquake", "fire"])
    bulk = any(k in text for k in ["bags", "boxes", "bulk", "lot", "many"])

    flags: list[str] = []
    assumptions: list[str] = []

    # Base scores
    scores = {p: 3 for p in PATHWAYS}
    reasons = {p: [] for p in PATHWAYS}

    # Baseline: money is flexible
    scores["Donate money"] += 2
    reasons["Donate money"].append("Money is flexible and lets organizations buy exactly what’s needed.")

    # Urgency / disaster
    if urgent or category == "Disaster relief":
        scores["Donate money"] += 2
        reasons["Donate money"].append("In acute disasters, cash is often the fastest and least wasteful.")
        flags.append("Urgency/disaster signal detected: prioritize cash unless a responder explicitly requests specific goods.")

    # Goods locally: best when logistics are easy
    scores["Donate goods locally"] += 1
    reasons["Donate goods locally"].append("Local goods donation can work well when items match needs and drop-off is easy.")

    if mentions_pickup or bulk:
        scores["Donate goods locally"] += 1
        reasons["Donate goods locally"].append("Pickup/bulk logistics suggest local goods donation is feasible.")

    # Shipping intent: enables matching goods to better-fit regions, but adds friction
    if mentions_shipping:
        scores["Donate goods to a better-fit region"] += 1
        reasons["Donate goods to a better-fit region"].append("Willingness to ship can enable matching goods to higher-need regions.")
        scores["Donate goods locally"] -= 1
        reasons["Donate goods locally"].append("Shipping preference may reduce fit for local-only drop-off.")

    # Seasonality (lightweight) for clothing
    is_winter_month = month in ["November", "December", "January", "February", "March"]
    if category == "Clothing":
        if is_winter_month:
            scores["Donate goods locally"] += 1
            reasons["Donate goods locally"].append("Winter season may increase clothing demand (depending on climate).")
        else:
            scores["Donate money"] += 1
            reasons["Donate money"].append("Out-of-season clothing is often less useful than cash support.")
            flags.append("Seasonality risk: out-of-season clothing may be lower impact unless specifically requested.")

    # Volunteering
    if mentions_time:
        scores["Volunteer / give time locally"] += 3
        reasons["Volunteer / give time locally"].append("User expressed willingness to volunteer; local time can be high impact.")
    else:
        reasons["Volunteer / give time locally"].append("Time-based help depends on availability and local opportunities.")

    # Shipping goods penalty (friction)
    scores["Donate goods to a better-fit region"] -= 1
    reasons["Donate goods to a better-fit region"].append("Shipping physical goods adds friction and may be less efficient than cash.")

    # If location missing, reduce confidence
    if not location.strip():
        assumptions.append("Location not provided; guidance is generalized.")
        flags.append("Low context: without location, geography/climate fit can’t be assessed reliably.")

    ranked = []
    for p in PATHWAYS:
        ranked.append({
            "name": p,
            "score": max(0, min(10, scores[p])),
            "reasons": reasons[p],
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked, flags, assumptions

def format_ranked(ranked: list[dict]) -> str:
    lines = []
    for i, r in enumerate(ranked, start=1):
        rs = "; ".join(r["reasons"][:3])
        lines.append(f"{i}) {r['name']} — score {r['score']}/10 — reasons: {rs}")
    return "\n".join(lines)

def format_list(items: list[str]) -> str:
    return "\n".join([f"- {x}" for x in items]) if items else "- (none)"

def extract_constraints(intent, location, month, category, extra):
    """
    Simple interpretation layer to simulate the 'Intent Agent'.
    This is intentionally lightweight for MVP.
    """
    constraints = {
        "User intent": intent if intent else "Not specified",
        "Location": location if location else "Not specified",
        "Month": month,
        "Donation category": category,
        "Extra considerations": extra if extra else "None provided"
    }
    return constraints

# ----------------------------
# Prompt (LLM explanation layer)
# ----------------------------
def build_prompt(location: str, month: str, category: str, intent: str, extra: str,
                 ranked: list[dict], flags: list[str], assumptions: list[str]) -> str:
    avoid_list = DO_NOT_DONATE.get(category, [])
    avoid_bullets = "\n".join([f"- {x}" for x in avoid_list]) if avoid_list else "- (none)"
    tips_bullets = "\n".join([f"- {x}" for x in PACKING_TIPS])

    ranked_block = format_ranked(ranked)
    flags_block = format_list(flags)
    assumptions_block = format_list(assumptions)

    return f"""
You are Northpaw, a practical donation decision assistant.
Goal: Provide a first-pass donation pathway recommendation that is context-aware and efficient.

User context:
- Location: {location}
- Month: {month}
- Donation category: {category}
- User free-text intent: {intent or "None"}
- Extra considerations: {extra or "None"}

Hybrid engine inputs (DO NOT change the ranking; your job is to explain it):
Ranked pathways from scoring layer:
{ranked_block}

Flags / risks to address:
{flags_block}

Assumptions made:
{assumptions_block}

Hard constraints:
- Do NOT invent specific local org names or addresses.
- Provide a first-pass recommendation using stated assumptions. Then, if additional information could materially change the ranking, ask at most ONE clarifying question.
- If you proceed with assumptions, label them clearly.
- Be concise and structured.
- If confidence is Low, explicitly state what key information is missing and how it could change the ranking.

Include:
1) Top recommendation (1–2 sentences)
2) Ranked pathways (repeat the same order, short)
3) Tradeoffs (3–6 bullets)
4) Warnings / misalignment (if any)
5) Better alternative (if rejecting/flagging something)
6) Confidence: High / Medium / Low with a short reason
7) Optional: ONE follow-up question (only if needed)

Also include this quick reference (keep it short):
- What NOT to donate for category "{category}":
{avoid_bullets}
- Packing/labeling checklist:
{tips_bullets}

Finally, include “Org Scout” guidance:
- List 3–6 types of organizations to search for
- Provide 3–5 copy/paste search queries
"""

def call_llm(prompt: str) -> str:
    api_key = st.secrets.get("OPENAI_API_KEY", "")
    if not api_key:
        return "⚠️ OPENAI_API_KEY not set. Add it to Streamlit secrets to enable AI output."
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": "You are Northpaw, a calm, constraint-aware donation guide. You prioritize efficiency, clarity, and responsible impact. You do not invent organizations, locations, or unverifiable facts. You are concise and practical."
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        max_tokens=800,
    )
    return resp.choices[0].message.content

# ----------------------------
# Inputs UI
# ----------------------------
with st.form("donate_form"):
    intent = st.text_area(
        "What do you have / want to do? (free text)",
        placeholder="E.g., 2 bags of winter coats, prefer pickup, want to help locally. Or: I want to help after floods but don’t know how."
    )
    location = st.text_input("Where are you donating / where is the impact?", placeholder="San Diego, CA (or Tonga, or London...)")
    month = st.selectbox("When?", ["This month"] + [
        "January","February","March","April","May","June","July","August","September","October","November","December"
    ])
    category = st.selectbox("Primary donation category (if goods)", [
        "Clothing", "Hygiene items", "Food (shelf-stable)", "Baby/kids items", "School supplies", "Disaster relief"
    ])
    extra = st.text_area("Anything else to consider? (optional)", placeholder="Budget, pickup vs drop-off, bulk items, etc.")
    go = st.form_submit_button("Generate recommendation")

# ----------------------------
# Run
# ----------------------------
if go:
    if not intent.strip():
        st.error("Please describe what you have / what you want to do in the free-text box.")
    else:
        # Intent Agent
        with st.spinner("🐻 Northpaw is understanding your request..."):
            constraints = extract_constraints(intent, location, month, category, extra)

        st.subheader("🐻 How Northpaw interpreted your request")
        for key, value in constraints.items():
            st.write(f"**{key}:** {value}")

        st.divider()

        # Evaluation Agent
        with st.spinner("🐻 Evaluating donation impact..."):
            ranked, flags, assumptions = score_pathways(location, month, category, intent, extra)

        # Recommendation Agent
        with st.spinner("🐻 Preparing recommendation..."):
            prompt = build_prompt(location, month, category, intent, extra, ranked, flags, assumptions)
            output = call_llm(prompt)

        with st.container():
            st.subheader("✅ Northpaw Recommendation")
            st.write(output)

            if "Confidence: High" in output:
                st.success("🎯 Confidence: High")
            elif "Confidence: Medium" in output:
                st.warning("Confidence: Medium")
            elif "Confidence: Low" in output:
                st.error("Confidence: Low")

            st.markdown("### 🧭 Pathway Scores")
            for p in ranked:
                st.write(f"**{p['name']}**")
                st.progress(p["score"] / 10)

        with st.expander("🧾 Quick ‘Do Not Donate’ reminder"):
            st.write("\n".join([f"- {x}" for x in DO_NOT_DONATE.get(category, [])]))

        # Debug toggle (great for demos)
        debug = st.checkbox("Show engine details (debug)")
        if debug:
            st.subheader("🧠 Engine internals")
            st.write({"ranked_pathways": ranked, "flags": flags, "assumptions": assumptions})

        with st.expander("🔎 Org Scout (copy/paste searches)"):
            queries = [
                f"donate {category.lower()} near {location}" if location else f"donate {category.lower()} near me",
                f"donate money to local mutual aid near {location}" if location else "donate money to local mutual aid near me",
                f"volunteer opportunities near {location}" if location else "volunteer opportunities near me",
                f"food bank donation guidelines near {location}" if location else "food bank donation guidelines near me",
            ]
            for q in queries:
                st.code(q, language="text")

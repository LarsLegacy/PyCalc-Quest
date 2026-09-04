import random
import re
import base64
import builtins as _builtins
import hashlib
import secrets
import threading
import time
from datetime import date

import streamlit as st
import streamlit.components.v1 as components
from streamlit_sortables import sort_items

# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="PyCalc-Quest",
    page_icon="\U0001F40D",
    layout="wide"
)

TOPICS = ["Sequence", "Selection", "Repetition"]


DEFAULT_RATING = 500
GUEST_STARTING_RATING = 500

# =========================================================
# NARRATIVE LAYER
# ---------------------------------------------------------
# Pure flavor text layered on top of the existing game logic - no challenge
# content, scoring, or unlock rules change here. The frame: the player is a
# Coder pulled into "the Grid," a glitching digital realm that only runs on
# three power circuits (Sequence, Selection, Repetition). Fixing each level
# = stabilizing a node. Ties into the neon/terminal look already in
# inject_theme() rather than introducing a mismatched fantasy skin.
# =========================================================

MASCOT_NAME = "Pyxel"
MASCOT_EMOJI = "\U0001F40D"

WORLDS = {
    "Sequence": {
        "sector": "Sector 01",
        "title": "The Order Circuit",
        "tagline": "Nothing here runs unless it runs in the right order. One line out of place and the whole node locks up.",
    },
    "Selection": {
        "sector": "Sector 02",
        "title": "The Fork Node",
        "tagline": "Every path splits. Choose right, or the circuit fires down the wrong branch entirely.",
    },
    "Repetition": {
        "sector": "Sector 03",
        "title": "The Loop Core",
        "tagline": "The deepest, least stable sector. It only holds together if the loop closes cleanly.",
    },
    "Boss": {
        "sector": "Sector 00",
        "title": "The Core Breach",
        "tagline": "Sequence, Selection and Repetition, all in one place, all scrambled together. Three escalating stages stand between you and saving the Grid.",
    },
}

# The hidden 4th sector - not one of the three normal circuits, so it's
# deliberately kept out of TOPICS (which drives the 3-column sector select,
# the lesson flow, etc). It only ever gets touched once every real topic is
# fully complete.
BOSS_TOPIC = "Boss"
BOSS_LEVEL = 1  # first boss stage - the entry point into the Core Breach node map
FINAL_BOSS_LEVEL = 3  # last boss stage - clearing this is what finishes the whole sector
ALL_TOPICS = TOPICS + [BOSS_TOPIC]  # for anything that needs to track/reset progress on every topic, boss included

LEVEL_TITLES = {
    "Sequence": {
        1: "Boot Sequence", 2: "Power Chain", 3: "Signal Intake",
        4: "Area Circuit", 5: "Full Uplink", 6: "Echo Protocol",
        7: "Sum Relay", 8: "Score Matrix", 9: "Price Ledger",
        10: "Core Rebuild",
    },
    "Selection": {
        1: "Adult Gate", 2: "Age Gate", 3: "Heat Sensor",
        4: "Teen Filter", 5: "Grade Splitter", 6: "Pass Checkpoint",
        7: "Sign Detector", 8: "Grade Matrix", 9: "Range Validator",
        10: "Full Diagnostic",
    },
    "Repetition": {
        1: "First Cycle", 2: "Sum Loop", 3: "Countdown Core",
        4: "Even Scanner", 5: "Times-Table Engine", 6: "Total Accumulator",
        7: "Loop Counter", 8: "While Gate", 9: "Running Total",
        10: "Loop Core Rebuild",
    },
    "Boss": {
        1: "Full System Override",
        2: "Peak Detection Core",
        3: "Final Override",
    },
}

MASCOT_LINES = {
    "welcome": [
        "The Grid's flickering out, Coder. Sequence, Selection, Repetition — the three circuits keeping it alive — are all destabilizing. You're the only one who can rewrite them back into shape.",
    ],
    "correct": [
        "Node stabilized. Circuit's flowing again.",
        "Clean fix. The Grid holds a little steadier now.",
        "That's it — logic locked in. On to the next node.",
        "Signal's steady. Nice work, Coder.",
    ],
    "wrong": [
        "Glitch detected. Recalibrate and try again.",
        "Not quite — the circuit's still misfiring.",
        "Close, but the logic's snagging somewhere.",
    ],
    "gameover": [
        "Connection lost. The node resisted this attempt — regroup and re-enter.",
        "The circuit overloaded. Happens to every Coder. Try the node again.",
    ],
}


def mascot_line(category):
    return random.choice(MASCOT_LINES[category])


def render_mascot(text, key=None):
    st.markdown(
        f'<div class="mascot-bubble">'
        f'<span class="mascot-avatar">{MASCOT_EMOJI}</span>'
        f'<span class="mascot-text"><b>{MASCOT_NAME}:</b> {text}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


# =========================================================
# ACCOUNTS (Supabase-backed, salted+hashed passwords)
# Guests never touch the database, so their progress is never saved.
# =========================================================

@st.cache_resource
def get_supabase_client():
    from supabase import create_client
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


def get_user(username):
    """Returns the user's row dict, or None if not found / DB unreachable."""
    try:
        supabase = get_supabase_client()
        res = supabase.table("users").select("*").eq("username", username).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        st.error(f"Couldn't reach the database: {e}")
        return None


def get_all_users():
    """Returns every user row, or [] if the DB is unreachable."""
    try:
        supabase = get_supabase_client()
        res = supabase.table("users").select("*").execute()
        return res.data or []
    except Exception as e:
        st.error(f"Couldn't reach the database: {e}")
        return []


def create_user(username, salt, pwd_hash, seed=None):
    """Creates a new account row. `seed`, if given, is a dict of progress
    fields (xp/rating/completed_levels/etc.) carried over from a guest
    session so signing up doesn't wipe what they already did."""
    seed = seed or {}
    supabase = get_supabase_client()
    supabase.table("users").insert({
        "username": username,
        "salt": salt,
        "password_hash": pwd_hash,
        "xp": seed.get("xp", 0),
        "rating": seed.get("rating", DEFAULT_RATING),
        "completed_levels": seed.get("completed_levels", {t: [] for t in ALL_TOPICS}),
        "achievements": seed.get("achievements", []),
        "streak_count": seed.get("streak_count", 0),
        "longest_streak": seed.get("longest_streak", 0),
        "last_play_date": seed.get("last_play_date"),
        "had_perfect_run": seed.get("had_perfect_run", False),
        "had_speed_run": seed.get("had_speed_run", False),
    }).execute()


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return salt, pwd_hash


def verify_password(password, salt, expected_hash):
    _, pwd_hash = hash_password(password, salt)
    return secrets.compare_digest(pwd_hash, expected_hash)


def load_user_progress(username):
    data = get_user(username) or {}

    st.session_state.xp = data.get("xp", 0)
    st.session_state.rating = data.get("rating", DEFAULT_RATING)

    # Make sure every current topic exists,
    # even if the user's saved data is from an older version.
    saved_levels = data.get("completed_levels") or {}

    st.session_state.completed_levels = {
        topic: saved_levels.get(topic, [])
        for topic in ALL_TOPICS
    }
    st.session_state.achievements = data.get("achievements") or []
    st.session_state.streak_count = data.get("streak_count", 0)
    st.session_state.longest_streak = data.get("longest_streak", 0)
    st.session_state.last_play_date = data.get("last_play_date")
    st.session_state.had_perfect_run = data.get("had_perfect_run", False)
    st.session_state.had_speed_run = data.get("had_speed_run", False)


def persist_progress():
    """Writes current xp/rating/completed_levels/achievements/streak back to
    Supabase. No-op for guests or anyone not logged in."""
    if st.session_state.get("is_guest") or not st.session_state.get("username"):
        return
    try:
        supabase = get_supabase_client()
        supabase.table("users").update({
            "xp": st.session_state.xp,
            "rating": st.session_state.rating,
            "completed_levels": st.session_state.completed_levels,
            "achievements": st.session_state.achievements,
            "streak_count": st.session_state.streak_count,
            "longest_streak": st.session_state.longest_streak,
            "last_play_date": st.session_state.last_play_date,
            "had_perfect_run": st.session_state.had_perfect_run,
            "had_speed_run": st.session_state.had_speed_run,
        }).eq("username", st.session_state.username).execute()
    except Exception as e:
        st.error(f"Couldn't save progress: {e}")


# =========================================================
# EMBEDDED AUDIO (synthesized 8-bit style SFX/BGM, base64 WAV)
# =========================================================

AUDIO_B64 = {
    "pop": "UklGRggHAABXQVZFZm10IBAAAAABAAEAESsAABErAAABAAgAZGF0YeQGAACAhIiOkpmfo6SkrbSzuLjOysYoMy8hFhkNFBsUFw8iEiEhHSjv3tbf2+bo2uXf2O3g3Nrn1+7TFxYcHBspHxwjKCAtGxgjFh0bKtTV0tbp4+Dc1unV3dnQ0d7d2eQdJCcmLicbJSYlISMaLh8uIysi3szj09Hh1t/b0dLV3uPS283R1iEwKyYxJCAhLSopJTUxKjUyJi/X28nT19nV1NLI2NXS28nT08Xc1S0mOCY0NywvNSozKy4xKSktOivPw9HHzNbJy8TCxsTPzs7FyMbP1jA9OSw/MD89Miw1Lj4vNzA7NjQv0MTJysfFx83IwMTCyczDyMLHwLxBNzYzQjBCNTxENkE2PTtDQDk9PcbDx8a/vcvCw8C9ubnKv7y+xL7BQTo+Qz49OERGRj1EQ0NFREJIOjw8vbu2ubbEtcS/w720vb+8u7W2tsBIPT5LSEFBS0RBS0VISkw/RD9HTEG3ubaxvb+7s7e9sq++vLa5ubK9ubxBRUxLSURBTktDT0dDQk9JRk5JTUq8sq+3vrSwurq3vrq5tb29ubK5uLS1Q09AQUpJQ0lIRkpJT0VOQkhORENNtLS1t7e9vLm0trG8t7GytLi+vrm/uUZDQ0pFRE9BTEJKRUZJREBITEZGTky/tr6wvL2wsb+ytri0v7W5s7y/vri9Sk1LQ0lFTkVGQk9MTUpGTkBBSkdHS7q9s7u1tLq/tLu6s7y3sbWwtbi1ubJFREJDSEZMTUtGSEhFS01JTUxGS0pITL69urK9sb62vLC1sb+9u7K3tLWwvLW5Rk9ET0FCREFITE9LSEFGS0pHR0JJSke8sLq4vru+tL6+vr22sLm0v7Oyu727uEZPQklBRExJRkdJT0RLT0tDSUlCT09ERrWzsbi/tbq2s7O4v7i+s7mwvLWyuLW2sEdOQERLQk1FSEJFTURPRk9MR0xISkxHQrm/sLG/sLS4ubW4tbW9uL+1tby0uLiytEdER0dLS05EQUtITExBSkxESENPSkNATUe9vr2+s76wsry0v7W9u7+7srO+vLS/sLi3QkdDRUxDTUNITUBJTEhGRkVAS0ZPTkpIR7G2tbq0uLKytLq3vbK9uLi8trS+t7G1u7m+R0xGTklFRkBORE9LT0lPQkZPTEJMQU1PQ0mwtbOxubS8sbKyubC6s7C7u7u0vrC7u7a8tU1NSEpITU5HQk9MRk1DUENJQk5HSkdOQkVItr64tbm6s7a5ub2xu7SxsLuwu7mzsL+ztrWyQEJFSklHQE5ASkhPRUBER0tIQkFPTkdAT0dDsrq6tba+vbG6s7m0vLG5sLG4sLKxsr++vbu0sk1GTE1BQUJCTU1NREZFR0lCTUJMQ09JTkJMTUO5u7q7tLuxt7O4t7i/tb2+trW6srCxvbu/v7GzSkNBQ0JHR0tJS0lCTExPR0VHS0FFTE9MSENMSki8srm0vru9sb22vre+uL20uLm0urO/sbuxvru9vEdCSE5KTU1QTlBPRE1JQklMT0lOTUdDQ1FHRkZESa+xr7q0tLC5uLatrrG5r7G4rbKst7a4r7evr7iysk1UUkdLTExPSUpLTlJITUtIT1RJU1JOVFRLTk9VS0quqrKpqbGssqyor7KurK2wqayzsKmzrbOvrayqrauvVlJQU1NUTlRXVFlaVVVYV1VRVFZWWlpWWU9QWFVbU1upqaqspa2krqiurKitq62tqqarraOop6ikraOmqKOoo6dVVVZUV1tZU1xXVFVWW1ZYVlRZWVlYVVxeWF1XXFlaXlaloqKoo6GkqKWgoqafpqSnpKWln6Chn6Smo6OgoKagoaOeW1peYF5bY1xiYGFbXF9jXFtbYVxhXF9cYFxfYFxkY11hY2Ocop6cmqGemp+anaGcnZ2boZ+ZmZ+dn6Cenp6bm5mdmJ2YmmdgYGZmY2FmZ2VkaGZkY2hnZ2dnZGZjZ2RmZmllZmpkaWNkZZiWl5uVmZeVlJeYmZWamZeYmpeZmZSZmJmUmZWTlpeTmZSXl5SXampqbGxsaWpsa2hoa2lsbmtqbmxqbWtsampsbmxrbWtubmxsbGuRlJSQkY+Qko+RkZCPkZGRkJGSj5GRj5CQjo+PkpCRjY+Pjo6PjY5vcHBwcHBxcnFxcnByc3Jzc3NycnNzdHRxdHNzdHJxdXJ0cnJ0dHNzdIyMi4uJjImMiouLi4uKiomKi4uLi4qKioqJioqIiIqIh4eJh4iIiImId3Z4d3h4d3l5eHh4eXd4eHl4eHl4eXp6enp6enp5enp6e3t7enp6e3t7e3qEg4OEhIODhIODg4ODg4OCg4KCg4OCgoKCgoKCgoKBgoGBgYGBgYGBgYGAgH9/f39/f39/f4A=",
    "success": "UklGRr0OAABXQVZFZm10IBAAAAABAAEAESsAABErAAABAAgAZGF0YZkOAACAgoOEf316dnJtZ3J1em1xdn2Di5Ods6ylfHJnW09BM1djb09caXiHl6e55dfFe2pZSDcmFkdYaUNUZXaHmKm65dTDfm1dTDwrG0ZXaEVVZnaHl6e44tLCgHBgUEAwIEZWZkZWZnaGlqa24NDAgnJjU0Q0JUZVZXRYZ3eGlqW03c2+hHVmV0g5KkVVZHNZaHeGlaSz2su8hndpWkw9LyBUYnFaaXeGlKOx1si6iHpsXlBCNCZTYW9caniGlKKv08W3inxuYVNGOCtTYG5da3iGk6Gu0MO1i35xZFdKPTBSX2xfbHmGk6CtzcCzjYB0Z1tOQjVSXmtgbXqGkp+ryb2wpIN2al5SRjpRXWpibnqGkp6qyLywpIR4bGBURztRXWlhbXmFkZ2pyb2xpYV5bWBUSDxQXGhgbHiEkJyotL6ypYZ5bWFVST1PW2dfa3eDj5yotL6ypoZ6bmJWSj5OWmZeanaDj5uns7+zp4d7b2NXSz9NWWVdanaCjpqmssC0qIh8cGRYTEBNWWVdaXWBjZiksL+zqIl9cWZaT0NOWWVwaXWAi5eirb2yp4l+c2hcUUZPWmVwaXR/ipWgq7yxpol/dGlfVEo/W2ZwaXR+iZOeqLqvpYp/dWthV01DXGZwanR+iJKcpbiupIqAdm1jWVBGXWdwanR9h5Cao7aso4qBd25lXFNJXmdwanR9ho+YobSrooqBeHBnXlVNX2hwa3R8hY2WnrKpoYqCeXFpYFhQYGhxa3R8hIyUnLCon5eCenJqY1tTYWlxbHR7g4uSmq2mnpeDe3RsZV5WYmpxbXR7goqRmJ+knZaDfHVuZ2BZZGtybXR7gomPlpyim5WDfXZwaWNcZWxybnV7gYeOlJqgmpSDfXdxa2VfZ21zb3V7gYaMkpiemJKDfnhzbWhiaG5zcHV7gIaLkJWcl5GDfnl0b2plam90eXZ7gIWKjpOalZCDf3p1cWxoa3B1eXZ7f4SIjZGYk4+Df3t3c25qbXF2end7f4OHi4+VkY2Df3x4dHFtaXN2enh7f4KGiY2Tj4yDgHx5dnNwbHR3e3l8f4KFiIuRjYqDgH16d3Vyb3Z4e3l8f4GEhomOi4mCgH57eXd0cnd5fHp9f4GDhYeMiYeCgH58enl3dXl7fHt9f4OGg4OEfndwdnhucXV6gIuno5p6cGZbTkFteGBsd4WUpc+/gHBeSjUgR1xyT2Z8kqe85M2AalQ/KRVKYHVVa4CVq/DbxnxnUj0pFFJnSF1yhpuw59K9d2NOOiZDWGxQZHiNobXeyYZzX0s3JEpdcVdrf5OmutXBgm5bSDUhT2NLX3KFmKvgzbp9alhFMiBVaFNleIuesNfFsnlnVEIwSFptWmx+kaO1z72HdWNSQC5OX3FhcoSWp9nHtYNyYE8+LVNkVmd5ipus0b+uf25dTTwrWGldbn6PoLDJuIx8a1tLOkxcbWN0hJSktMGxiHhoWUk5UWFaaXmJmajJuqqFdWZXRzhWZWBvf46drMOzpIFyY1NES1ppZXSDkqGxvq+MfW5eT0BPXm1peIeWprW6q4h5aVpLPFNiXm18i5uqxbanhHRlVkc4V2dicYCQn67Bso9/cGFSQ0xca2Z1hZSjsr2uintsXU4+UWBvanqJmKfIuamGd2hZSTpVZF9vfo2cq8S0pYJzZFVGN1ppZHOCkaCuva+Nfm9hUkRQX21pd4aUorG4qYh6bF5QQlZkX258iZelwLKkhHZpW05AW2hkcn+Nmqi6rJ+Ac2ZZTFJgbWl2g5CdqrSnin1wY1dKWGRxbXqGk5+8r6KGeW1hVUlcaWVxfYmVobaqnoJ2a19TR2FtaXWBjJijsaWKf3RoXVJaZXFteISPmqWsoId8cWZbUV9pdHF8hpGcsqechHlvZFpQY21qdH+Jk52sopiBd21jWV1ncW54gYuVn6ieiH51a2JYYWt0cXuEjZago5qFfHNqYVhlbmt0fYaPmKifloJ5cWhgV2lxb3eAiJCZo5uTgHhvZ19kbHRyeoKKkpmfl4V+dm5nX2hwd3V8hIuTo5uUg3x0bWZfa3Jwd3+GjJOfmJGBenNtZl9udXN6gIeNlJuUhX95cmxma3F4dnyCiI6Ul5GDfXhybGZudHJ4foOJjpmUjoF8d3FsZ3F2dXp/hIqPlpGLgHt2cWxvdHl3fIGFio6SjoN/enZxbXJ2enl9goaKjo+Lgn56dnJudHh3e3+ChoqQjYmAfXl2cm93enl8gIOGiY2Kg398eXZzdnl8e36Ag4aJioiBf3x6d3V4en18f4GDhoqIhoB+fHp4eH17eHZzbnyDfoKGipGdlHRqX1RFa3lpeIiaqcCwdmJMNiBcclZthZ6548t4XEInDVNsT2mDnbfhyHlhRy0TVG1QaYKcteDHemFJMBhTa1Fqgpuz38Z8ZEw0HFFpUWmBmbHexn9nTzggUGhRaYCYr93FgWpSOyRPZlFpgJeu28SDbFU/KE5kUmh/lqzaxIVvWEIsTWNSaH6UqtnDh3FbRjBMYlJofpOp18KJdF5JNEtgU2h9kqfWwYt2YU04Sl9TaH2RptTAjHhkUDxJXnJofJCl07+remdTP0lccGh8kKO3vqp9aVZDMFtuaXyPorW8qX9sWUc0Wm1pfI6hs7uogW5cSjhZa2l7jqCyuqiCcF5MOlhqaHqMnrG7qYNxX007V2lneYudr72rhXNgTjxWaGZ4ipyuvqyGdGJQPVVnZXeJm62/rYd1Y1E/U2VkdoiarMCuiHZkUkBSZGN1h5mrwa+Jd2VTQVFjYXSGmKrCsIp4ZlRCUGJgcoSXqcOxi3lnVUNPYV9xg5WnxLKMe2lXRk9hX3GClKXDsY18a1lIT2BfcIGSo8Kxjn1sW0tQYHFvgJChwbGgfm5dTVBgcG9/j5+vsKB/b19QQGBwbn6NnaywoIBxYVJDYG9ufYybqrCggXJjVEZgb218i5mor6CCc2VXSGBubXuKmKauoIN1Z1lLYG5te4iWpK6gg3ZoW05gbm16h5SiraCEd2pdUGFubHmGk6Csn4V4a19TYW5seYWRnqufhXltYVVhbWx4hJCcqp+Gem5jV2JtbHiDj5qpnoZ7cGVaYm1sd4KNmKidh3xxZlxjbm13goyXp52HfXJoXmNubXeBi5WmnId9dGpgZG5td4CKk6WbiH51a2Jlbnd3gImSpJuSf3ZtZGZud3Z/iJCZmpF/d25mXm93dn+Hj5eZkYB4cGhgb3d2foaOlZiQgHlxamNwd3Z+hYyTl5CBenNsZXB3d32Ei5KWj4F6dG1ncXd3fYSKkJWOgXt1b2lyeHd9g4mPk46CfHZxa3J4d32CiI2SjYJ8d3Jtc3h4fYKHjJGMgn14dG90eXh9gYaKkIuCfnl1cXV5eX2BhYmOioJ+enZzdnl5fYCEh42Jgn57eHV3enp9gIOGi4iCf3x5dnh7en2Ag4WJh4GBfHdxbHZyeYKMnpt/b2Bpc2h2iJupfWxZR2xbbYOayLFtUzVPbFl5mbnXfVk2E1Q/YYSn68pxTitDZE9xlLbYgWA/HlR1YoOk6MdyUTEQY1Fyk7PXhGREI1JyYYKi5sZ2VjYXYFFxkbDVh2hJKVBvYYCf5MV5WzwdXlJwj67UtWxOL05sYX+d4sR9X0EjXFJwjqvStHBSNU1qYX6bucOAY0YqWlNvjKnQs3NXO0tnYX2atsGDZ0swWFNvi6fOsndbQEplYX2Ys8CGa1A1V3JviqXMsXpgRUljYnyWsb6Jb1U7VW9viaPKsH1kSzFhYnyVrryLc1pBVG1viKHHr4FoUDdfY3yUrLqOdl5GUmtvh5/Hr4NrUzpeYnqSqrykeF9HUWlthZ3JsIRsVDxcYHiQqb2leWFJT2drhJy0soZuVj5aX3ePp7+ne2NLTWVqgpqytIhwWD9ZXXWNpcGpfWRMTGRogJiwtopxWUFXb3OLpMKqfmZOSmJmfpevt4tzW0NVbXKKosSsgGhQOWFlfZSst411XkdVbHGIn8OsgmtUPWFle5Kpt453YUpVbHCGnMKrg21XQWBkepCltqB5Y05Va2+Ema6rhG9aRWBkeY6itaB7ZlJWam6Cl6uqhnFdSWBkeIyftKB8aVVWam2BlKiqh3NgTWBkd4qds6B+a1hXam2AkqSpiHVjUWBzdoiasqB/bVxKaW1+kKGoiHdmVWFydYaXsJ+Ab19OaWx9jp6niXloWGFydYWVr5+BcWJSamx8jJyml3prW2JxdIOTrZ6Cc2RVamx7ipmllnttXmNxdIKQn52DdWdZam17iZakln1vYWRxdIGOnJyEd2pca216h5SilX5xZGVxdICNmZuEeGxga3d6hpKglH9zZ2ZxdH+LlpqFeW5jbHd5hI+flIB1al9ydH6JlJiFe3BmbXd5g42dk4B2bGNydH6IkZeFfHJpbnd5goubkYF4b2ZzdX2Gj5WMfXRsb3h5gYqZkIF5cWl0dX2FjZOMfnZucHh5gYiPj4J6c2x1dn2Ei5KLfnhxcnh6gIeNjYJ7dW92d32DiZCKf3lzc3l6gIWLjIJ8d3J3fH2Ch42If3p2cXp7f4SIioJ9eXV4fH2BhYuHgHx4dHt7f4OGiIJ+e3d5fX2BhImFgH16d3x8f4KEhoF/fHp7fX6AgoaEgH58en19f4GDhIJ/fXx8fn6AgYKCgH99fH5+f4CBgoF/f35+f3+AgICAgH9/f39/f4CAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgA==",
    "fail": "UklGRg4NAABXQVZFZm10IBAAAAABAAEAESsAABErAAABAAgAZGF0YeoMAACAgoWHioyPkpSXmZyfoaSmqayusbNJRkRBPzw5NzQyLywqJyUiHx0aGBUSEA0NDQ4ODg7x8fHw8PDw8PDw7+/v7+/v7+7u7hEREREREhISEhISEhMTExMTExMUFBQUFBQUFRUVFerq6unp6enp6enp6Ojo6Ojo6OfnGBgYGBgZGRkZGRkZGhoaGhoaGhsbGxsbGxsbHBwc4+Pj4+Li4uLi4uLh4eHh4eHh4OAfHx8fHx8gICAgICAgISEhISEhISIiIiIiIiIjIyPc3Nzc29vb29vb29va2tra2tra2SYmJiYmJicnJycnJycoKCgoKCgoKCkpKSkpKSkqKtXV1dXV1NTU1NTU1NPT09PT09PSLS0tLS0tLS4uLi4uLi4vLy8vLy8vMDAwMDAwMDExzs7Ozs7Ozc3Nzc3NzczMzMzMzMw0NDQ0NDQ0NTU1NTU1NTY2NjY2NjY2Nzc3Nzc3NzjHx8fHx8fGxsbGxsbGxcXFxcXFxTs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O8TExMTExMTExMTExMTExMTExMTEOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O8TExMTExMTExMTExMTExMTExMTEOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7xMTExMTExMTExMTExMTExMTExMQ7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OzvExMTExMTExMTExMTExMTExMTExDs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O8TExMTExMTExMTExMTExMTExMTEOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7xMTExMTExMTExMTExMTExMTExMQ7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OzvExMTExMTExMTExMTExMTExMTExDs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O8TExMTExMTExMTExMTExMTExMTEOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7xMTExMTExMTExMTExMTExMTExMQ7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OzvExMTExMTExMTExMTExMTExMTExDs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OzvExMTExMTExMTExMTExMTExMTExDs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O8TExMTExMTExMTExMTExMTExMTEOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7xMTExMTExMTExMTExMTExMTExMQ7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OzvExMTExMTExMTExMTExMTExMTExDs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O8TExMTDw8PDw8PDw8LCwsLCwsLCPj4+Pj4+Pj4/Pz8/Pz8/P0BAQEBAQEBAQUFBQUFBvr69vb29vb29vby8vLy8vLy8u7tERERERERFRUVFRUVFRUZGRkZGRkZGR0dHR0dHR0e3t7e3t7e3t7a2tra2tra2tbW1tUpKSkpLS0tLS0tLS0xMTExMTExMTU1NTU1NTU1NTrGxsbGxsbGwsLCwsLCwsK+vr6+vUFBQUVFRUVFRUVFSUlJSUlJSUlNTU1NTU1NTVFRUq6urq6uqqqqqqqqqqqmpqampqampV1dXV1dXV1dYWFhYWFhYWFlZWVlZWVlZWlpaWlpapaWkpKSkpKSkpKOjo6Ojo6OjoqJdXV1dXV1eXl5eXl5eXl9fX19fX19fYGBgYGBgYGCenp6enp6enp2dnZ2dnZ2dnJycnGNjY2NkZGRkZGRkZGVlZWVlZWVlZmZmZmZmZmZnZ5iYmJiYmJeXl5eXl5eXlpaWlpaWaWlqampqampqamtra2tra2trbGxsbGxsbGxtbW1tkpKSkpGRkZGRkZGRkJCQkJCQkJBwcHBwcHBwcHFxcXFxcXFxcnJycnJycnJzc3Nzc3OMjIuLi4uLi4uLioqKioqKioqJiXZ2dnZ2dnd3d3d3d3d3eHh4eHh4eHh5eXl5eXl5eYWFhYWFhYWFhISEhISEhISDg4ODfHx8fH19fX19fX19fn5+fn5+fn5/f39/f39/f4CAgoWHioyPkpSXmZyfoaSmqayusbO2ubu+wDw5NzQyLywqJyUiHx0aGBUSEA0NDQ4ODg4ODg4PDw8PDw8PEBAQ7+/v7+7u7u7u7u7u7e3t7e3t7ezs7Ozs7BMUFBQUFBQUFRUVFRUVFRYWFhYWFhYWFxcXFxcXFxgYGBgYGBgZ5ubm5ubm5eXl5eXl5eTk5OTk5OTk4+Pj4+McHB0dHR0dHR0eHh4eHh4eHx8fHx8fHx8gICAgICAgISEhISEhId3d3d3d3d3c3Nzc3Nzc29vb29vb29va2tolJSUlJiYmJiYmJicnJycnJycoKCgoKCgoKCkpKSkpKSkqKioqKtXV1NTU1NTU1NPT09PT09PS0tLS0tLS0tEuLi4uLi4vLy8vLy8vMDAwMDAwMDExMTExMTExMjIyMjIyMjMzM8zMzMzLy8vLy8vLysrKysrKysnJycnJycnJNzc3Nzc3Nzg4ODg4ODg5OTk5OTk5Ojo6Ojo6Ojs7Ozs7Ozs7OzvExMTExMTExMTExMTExMTExMTExMTExMTEOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OzvExMTExMTExMTExMTExMTExMTExMTExMTEOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OzvExMTExMTExMTExMTExMTExMTExMTExMTExDs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7xMTExMTExMTExMTExMTExMTExMTExMTExDs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7xMTExMTExMTExMTExMTExMTExMTExMTExDs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7xMTExMTExMTExMTExMTExMTExMTExMTExMQ7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O8TExMTExMTExMTExMTExMTExMPDw8PDw8M8PDw8PDw9PT09PT09PT09PT09Pj4+Pj4+Pj4+Pj4+Pz8/Pz8/P8DAwMDAwL+/v7+/v7+/v7+/v7++vr6+vr6+QUFBQUFBQkJCQkJCQkJCQkJCQkNDQ0NDQ0NDQ0NDQ0NERERERES7u7u7u7u7urq6urq6urq6urq6ubm5ubm5RkZGRkZGRkdHR0dHR0dHR0dHR0dISEhISEhISEhISEhISUlJSUm2tra2tra2trW1tbW1tbW1tbW1tbW0tLS0S0tLS0tLS0tMTExMTExMTExMTExMTU1NTU1NTU1NTU1NTU5OTk6xsbGxsbGxsbGwsLCwsLCwsLCwsLCwr6+vr1BQUFBQUFBQUFFRUVFRUVFRUVFRUVFSUlJSUlJSUlJSUlJTU1NTrKysrKysrKysq6urq6urq6urq6urq6qqqlVVVVVVVVVVVVVWVlZWVlZWVlZWVlZWV1dXV1dXV1dXV1dXV1hYp6enp6enp6enp6ampqampqampqampqalpVpaWlpaWlpaWlpaW1tbW1tbW1tbW1tbW1xcXFxcXFxcXFxcXFxdoqKioqKioqKioqKioaGhoaGhoaGhoaGhoaBfX19fX19fX19fX2BgYGBgYGBgYGBgYGBhYWFhYWFhYWFhYWFhYp2dnZ2dnZ2dnZ2dnZycnJycnJycnJycnJxkZGRkZGRkZGRkZGRkZWVlZWVlZWVlZWVlZmZmZmZmZmZmZmZmZpiYmJiYmJiYmJiYmJiXl5eXl5eXl5eXl5doaWlpaWlpaWlpaWlpaWpqampqampqampqampra2tra2tra2tra5SUk5OTk5OTk5OTk5OTkpKSkpKSkpKSkpKSbW5ubm5ubm5ubm5ubm5vb29vb29vb29vb29vcHBwcHBwcHBwcHCPj46Ojo6Ojo6Ojo6Ojo6NjY2NjY2NjY2NcnJzc3Nzc3Nzc3Nzc3NzdHR0dHR0dHR0dHR0dHV1dXV1dXV1dXWKioqJiYmJiYmJiYmJiYmJiIiIiIiIiIiIiHd3d3h4eHh4eHh4eHh4eHh5eXl5eXl5eXl5eXl6enp6enp6enp6hYWFhISEhISEhISEhISEhIODg4ODg4ODg3x8fHx9fX19fX19fX19fX19fn5+fn5+fn5+fn5+fn9/f39/f39/gICAgIA=",
    "gameover": "UklGRr8kAABXQVZFZm10IBAAAAABAAEAESsAABErAAABAAgAZGF0YZskAACAgYKCgoGAfnx5dXFsam1wc3d7gYaNk5ujq6agmpKLgnlwZltQRUFKVF9qdYGOm6m3xtbMv7KklYV2ZVRCMB4XJzhKXG+BlKa5y93w49G/rJqHdWNRPiwaEyU3SlxugJKktsja7OLQvqyaiHZkU0EvHRQmOEpcbX+Ro7TG2Onh0L6sm4l4ZlVDMiAVJzhKW21+kKGyw9Xm4M++rJuKeWhWRTQjFyg5SltsfY6fsMHS49/Ovayci3ppWEc3JhgpOkpbbHyNnq6/z+Dezb2snIt7alpKOSkZKjpLW2t7jJysvM3d3c28rJyMfGxcTDwsHCs7S1tre4uaqrrK2tzMvKycjX1tXU4+Lx8sO0tbanqJmai4x9fay7usnY1+bl9QQTEiLTxLW2p5iJentsXU2cq7rJ2Of3BhUkM0JS49TFtqeIeWpbPC0djJuqydjoBxYlRFNygvPkxbaXiGlaOxwM7WyLqrnY+AcmRWSDkrMD9NW2l3hZOhr73L1ce5q52PgXNlWEo8LjJATVtpd4SSoK27yNPGuKudj4J0Z1lMPzEzQU5baXaDkZ6rucbSxbeqnZCDdWhbTkE0NEJPXGl2g5CcqbbD0MO3qp2Qg3ZqXVBENzZDT1xpdYKOm6e0wM3CtqmdkIR3a19SRjo3RFBcaXWBjZmmsr7KwbWpnJCEeGxgVEg8OERQXGh0gIyYpLG9ycG1qZ2RhXltYVVJPTdDUFxodICMmKSwvMjCtqqekoZ6bmJWST03Q09bZ3N/i5ejr7vHw7ernpKGem5iVko+NkJOWmZyfoqWoq67x8O3q5+Th3tvY1dLPzVBTVlmcn6KlqKuusbEuKyglIh8cGRYTD81QU1ZZXF9iZWhrbnFxbmtoZSIfHBkWExANEBMWGRwfIiUoKy4xcW5raGViX1xZVlNQTU/S1djcHyIlKCsuMTGuq6ilop+cmZaTkI1P0tXY297h5Ofq7fDx7uvo5eKfnJmWk5CNj5KVmJueoaSnqq2wse7r6OXi39zZ1tPQzc9SVVhbXqGkp6qtsLIvLCkmIyAdGhcUEQ5PklVYW15hZGcqLTAx7uvpJiMgHVpXVJGOz5KVmFteISQm6eyvsa7r6SYjYF2al9TSD0/SlZhbXiDj5qlsbzGuq+kmI2CdmtgVUo/P0tWYWx3g46ZpK+6xbqvo5iNgndsYVZLQEBLVmFsd4KNmKOtuMO5rqOYjoN4bWNYTUJBTFZhbHeBjJehrLbBuK6jmY6DeW5kWU9EQkxXYWx2gYuVoKq1v7ito5mOhHpvZVtQRkJNV2FsdoCKlJ+ps723raOZjoR6cGZcUkhDTVdha3V/iZOdp7G7tq2jmY+Fe3FnXVRKRE5YYWt1f4mSnKavubasopmPhXxyaF9VTEVOWGJrdX6IkZukrre1rKKZj4Z8c2lgV01GT1hia3V+h5Cao6y1tKuimI+GfXRqYVhPR1BZYmt0fYaPmaKrtLOqoZiPhn10a2NaUUhQWWJrdH2Gj5egqbKzqqGYj4d+dW1kW1JKUVpja3R8hY6Wn6ewsqmhmJCHfnZtZV1UTFJaY2t0fISNlZ6mrrGpoJiQh393bmZeVk5TW2NrdHyEjJScpKywqKCYkId/d29nX1dPU1tja3N7g4uTm6Orr6efl5CIgHhwaGFZUVRcZGxze4OKkpqhqa6nn5eQiIB5cWpiW1NVXWRsc3uCipGZoKetpp6Xj4iBeXJrY1xVVl1lbHN6gomQl5+mrKWel4+IgXpzbGVeV1deZWxzeoGIj5adpKuknZaPiIF6dG1mX1hYX2Zsc3qBiI6VnKOpo52Wj4iCe3RuZ2FaWV9mbXN6gIeOlJuhp6OclY+Ignx1b2hiXFpgZ21zeoCGjZOZn6aim5WPiYJ8dnBpY11bYWdtc3qAhoySmJ6koZuVj4mDfXdxa2VfXGJobnR5f4WLkZedoqCalI6Jg313cWxmYF1iaG50eX+FipCVm6GfmZSOiIN9eHJtZ2JeY2ludHl/hIqPlJqfnpmTjoiDfnhzbmljX2Rpb3R5foSJjpOYnZ2Yk42Ig355dG9qZWBlam90eX6DiI2Sl5ycl5KNiIN+enVwa2ZiZmtwdHl+g4eMkZaam5aRjYiDf3p2cWxoY2dscHV5foKHi5CUmZqVkYyIg397dnJuaWVobHF1eX6ChoqPk5eZlJCMiIR/e3dzb2tnaW1xdXl+goaKjpKWmJSPi4eEgHx4dHBsaGpucnZ6fYGFiY2QlJaTj4uHg4B8eHVxbWprb3J2en2BhYiMj5OVko6Kh4OAfHl2cm9rbHBzdnp9gYSHi46RlJGNioeDgH16dnNwbW1wdHd6fYCEh4qNkJOQjYmGg4B9end0cW5ucXR3en2Ag4aJjI+Rj4yJhoOAfnt4dXNwcHJ1eHt9gIOFiIuNkI6LiIaDgH57eXZ0cXFzdnh7fYCChYeJjI6MioiFg4B+fHl3dXNydHd5e32AgoSGiIuNi4mHhYOAfnx6eHZ0c3V3eXt9gIKFiIuNjo2KhoJ+eXRuaGFcXF5iaG10eoGJkJmhqrS8vbWtpZyTioB1al9US0E4LTA7RlJea3iFkZ2otcHP3Org0sOzpJaJfG5hVEc5LB8UJDI/TVpndYKPnKq3xNHh6NvNwLOmmIt+cWNVRjcnGBglMj9NWmd0g5KhsL/O3ezm2cy+sKKThHVnWEo7LR4QGyo4R1VkcoGPnau6yNXi693PwLKkloh6bF5RRDcqHRooNkRSX217iJShrrvI1eLg0sW3qp2Qg3ZpXE9CNSkcIzA9SldkcX6LmKWyv8zZ5djLvrGkmIt+cWRYSz4yJR4rOERRXmp3hJCdqbbDz9vd0MS3q56ShXlsYFNHOy8iJjM/S1hkcH2JlaGtusbS3tXJvLCkmIyAdGhcUEQ4LCIuOkZSXmp2go6apbG9ydTZzcG1qp6ShntvY1hMQTUpKjZBTVlkcHuHkp6ptcDL19HGuq+jmI2BdmtfVEk+MycyPUhTX2p1gIuWoa24w87Vyr+0qZ2Sh3xyZ1xRRjswLjlET1pkb3qFkJqlsLrF0M3DuK2jmI2DeG1jWE5DOS81QEpVX2p0f4mTnqiyvcfRxryyp52TiH50amBVS0E3MjxGUVtlb3mDjZehq7W/ycm/tauhmI6EenBmXVNJPzY5Q01WYGp0fYeRmqStt8HKw7mvppyTiYB2bGNZUEY9NT9IUltlbniCi5WeqLG7xMi+tauimI+Fe3JoX1VMQjk5Q0xWX2lzfIaPmaKstb/JxLqxp56UioF3bmRbUUg+ND1HUFpkbXeAipOdprC6w8nAtq2jmZCGfXNqYFdNQzo4QUtVXmhxe4SOl6GrtL7HxbyyqJ+VjIJ5b2ZcUkk/NjxGT1libHV/iJKcpa+4wsvBt66km5GIfnVrYVhORTs3QEpTXWZweYONlqCps7zGxr2zqqCXjYR6cGddVEpBNztETldhanR+h5GapK23wMrCua+mnJOJf3ZsY1lQRjw1P0hSW2VveIKLlZ6osbvFyL61q6KYjoV7cmhfVUtCODlDTVZgaXN8ho+Zoqu1vsjDubCmnZOKgXduZVtSST82P0lSW2Rud4CKk5ylrrjBxr20q6GYj4Z9dGphWE9GPTxFTldgaXJ7hI2Wn6ixusPBuK+mnZSLgnlwZ15VTUQ7QUpTXGVtdn+IkZmiq7S8xLuyqqGYj4d+dW1kW1NKQj5GT1hgaXJ6g4uUnKWttr6/tq2lnJSLg3pyamFZUEhAQ0xUXGVtdn6Gj5efp7C4wLmxqaCYkIh/d29nX1ZORkBIUVlhaXF5gYqSmqKqsrq8tKyknJSMhHx0bGRcVExERU1VXWVtdX2FjZWcpKy0vLevp6CYkIiAeXFpYVpSSkNKUlpiaXF5gIiQl5+mrra6squjm5SMhX12bmdfWFBJSE9XXmZtdXyDi5Kaoaiwt7Wupp+XkImBenNrZF1WTkdMVFtianF4f4aOlZyjqrG3sKmim5SMhX53cGliW1RNSlFYX2ZtdHuCiZCXnqWss7OspZ6XkImCe3RuZ2BZUkxPVlxjanF4foWMkpmgp620rqehmpONhn95cmtlXlhRTVNaYGdudHuBiI6Vm6KorrCqo52WkImDfXZwaWNdVlBRV15ka3F3foSKkJedo6mvrKWfmZONhoB6dG5oYVtVT1VcYmhudHqAhoySmJ6kqq6noZuVj4mDfnhybGZgWlRUWl9la3F3fYOIjpSaoKWrqaOemJKMh4F7dXBqZF9ZVFhdY2ludHp/hYuQlpuhpquloJqVj4mEfnl0bmljXlhWXGFnbHJ3fIKHjJKXnKKnp6Gcl5GMh4F8d3JtZ2JdWFpgZWpvdHp/hImOk5idoqejnpmTjomEf3p1cGtmYVxZXmNobXJ3fIGGi4+UmZ6jpJ+alZCMh4J9eHRvamVhXF1iZmtwdXl+g4eMkZWan6OgnJeSjomEgHt3cm5pZWBcYGVqbnN3fICFiY2SlpufoZ2YlI+Lh4J+enVxbWhkYGBkaG1xdXl+goaKjpOXm5+emZWRjYmFgHx4dHBsaGRgY2drb3N3e3+Dh4uPk5ebnpqWko6Kh4N/e3dzb2toZGJmam5ydnp9gYWJjJCUl5ubl5OQjIiFgX16dnJva2hkZmltcXR4e3+DhoqNkZSXm5iUkY2KhoN/fHh1cm5raGVpbHBzdnp9gISHio6RlJeYlZGOi4iEgX57eHRxbmtoaWxvcnV4fH+ChYiLjpGUl5WSj4yJhoOAfXp3dHFua2lsbnF0d3p9gIOGiIuOkZSVko+MioeEgX98eXZ0cW5sbG5xdHZ5fH6BhIaJi46Rk5KPjYqIhYOAfnt5dnRxb2xucXN2eHt9gIKEh4mLjpCSj42LiIaEgX99enh2dHJvb3FzdXh6fH6Ag4WHiYuNj4+Ni4mHhIKAfnx6eHZ0cnBxc3V3eXt9f4GDhYeJi42OjYuJh4WDgX9+fHp4dnVzcnR1d3l7fX6AgoOFh4iKjIyKiYeFhIKAf318enp6eXh4ent7e3t6eXh2dHFua2lsbW9wc3V4e3+Dh4yRl52jqrS3s66ppJ6YkYqDe3NqYVdLPzIlJi42P0hSXGZxfIeUoa+8ydfk8ejd0ca7sKSZjH9yZVhLPjEkFw0YJC86RlJfbHmGk6CsucbS3+zv5NnMv7OmmY2AdGdbTkI2KR0RFCEtOkZSX2t3g5CcqLTAy9bh7OTYzMC0qJyQhHhsYFVKQDUqHxUhLThEUFtnc36JlJ+qtcDK1eDl2c7Ct6yhlouAdWpfVEo/NCkeHyo1QEtVYGt2gYyXoay3ws3X4t3Sx7yxp5yRhnxxZlxRRjwxJxwmMTxGUVtmcXuGkJulsLrEz9nf1crAtauhloyBd21jWE5EOi8lJC44Q01XYWx2gIqUnqiyvMfR29fNw7mvpZuRh31zaV9VS0E4LiQsNT9JU11ncXuEjpiiq7W/yNLZ0Ma8sqmflYyCeW9lXFJJPzYsKTM9RlBZY2x2f4iSm6Wut8HK09LIv7aso5qQh351a2JZUEc+NSwxOkNNVl9ocXqDjJWep7C5wsvTysG4r6adlYyDenFoX1dORTw0LzhBSlNbZG12foeQmKGqsrvDzMzDu7KpoZiQh392bmVdVExEOzM3P0hQWGFpcnqCipObo6u0vMTMxb20rKSck4uDe3NrY1tTS0M7NT1FTVZeZm52foaOlp6mrra+xsjAuLCooJiQh393b2dfV09HPzc5QUlRWWFpcXmBiZGZoqqyusLKxLy0rKSclIyEfHRsZFxUTEQ7NT1FTVVdZW11fYWNlZ2lrbW9xcjAuLCooJiQiIB4cGhgWFBIQDg4QEhQWWFpcXmBiZGZoamxucHJxb21raWdlY2FfHRsZFxUTEQ8NDxETFRcZGx0fISMlJylrbW9xcnBubGpoZmRiYF5cWlhWVFJQTk4QEhQWGBocHiAiJCYoKiwuMDIxr21raWdlY2FfXVtZV1VTUU9NTtDS1NbZGx0fISMlJykrLS8xMrCurKqopqSioJ6cWlhWVFJQTk3P0dPV19nb3d/h4+Xn6evt7/Hxb21raWdlo6GfnZuZl9XT0c/OD1ETFRcZGxze4OLkpqiqbG5wMfAuLCpoZmRioJ6c2tkXFRNRT46QkpRWWBocHd/ho6VnaSss7vCwrqzq6SclY6Gf3dwaGFaUktEPEBHT1ZdZWxze4KJkZifpq61vMO9ta6nn5iRioN7dG1mX1hRSUI+RUxTW2JpcHd+hYyTmqGor7a9vrewqaKblI2Gf3hxamRdVk9IQUNKUVhfZm10eoGIj5ado6qxuL65sqylnpeQioN8dm9oYVtUTUdCSE9WXGNqcHd+hIuRmJ+lrLK5u7Sup6Gak42GgHlzbGZgWVNMRkdNVFpgZ210eoGHjZSaoKets7q2sKmjnZaQioN9d3BqZF5YUUtFS1JYXmRrcXd9g4qQlpyiqK60t7GrpZ+Zk42GgHp0bmhiXFZQSkpQVlxiaG50eoCGjJKYnqOpr7Wzraehm5WPiYR+eHJsZ2FbVVBKT1VaYGZscXd9g4iOlJmfpaqwtK6oo52XkoyGgXt2cGtlX1pUT05TWV5kaW91en+FipCVm6Cmq7CvqqSfmZSOiYR+eXRuaWReWVRPUlhdYmhtcnd9goeMkpecoaarsKuloJuWkYuGgXx3cm1oY11YU1FWXGFma3B1en+EiY6TmJ2ip6yrpqGcmJOOiYR/enVwa2ZiXVhTVltfZGluc3h8gYaLkJSZnqKnrKeinpmUkIuGgX14c29qZmFcWFVaXmNobHF2en+DiIyRlZqeo6eoo5+alpGNiIR/e3ZybmllYFxYWV5iZmtvdHh8gYWJjpKWmp+jp6Sfm5eTjoqGgn15dXFtaGRgXFldYWZqbnJ2en6Dh4uPk5ebn6OkoJyYlJCMiISAfHh0cGxoZGBcXWFlaW1xdXh8gISIjJCTl5ufo6CcmZWRjYmFgn56dnNva2hkYF1hZGhsb3N3e36ChomNkJSYm5+gnZmVko6Lh4OAfHl1cm5rZ2RhYWRoa29ydnl8gIOHio2RlJibnp2ZlpKPjIiFgn57eHVxbmtoZGFkZ2tucXR4e36BhIiLjpGUl5qcmZaTkI2JhoOAfXp3dHFua2hlZGdqbnF0d3p9gIOFiIuOkZSXmpmWk5CNioeFgn98eXZzcW5raGZoa21wc3Z5e36BhIaJjI6RlJaYlpOQjouIhoOAfnt4dnNxbmxpaGttcHN1eHp9f4KEh4mMjpGTlZWTkI6LiYaEgn99enh2c3FvbGprbnBzdXd5fH6Ag4WHiYyOkJKUkpCOi4mHhYOAfnx6eHZ0cW9tbG5wc3V3eXt9f4GDhYeJi42PkZGPjYuJh4WDgX99fHp4dnRycG5vcXN1d3l7fH6AgoSFh4mLjY6Qjo2LiYeGhIKAf317enh2dXNxcHJ0dXd5enx+f4GChIWHiIqMjY2MiomHhoSDgYB+fXt6eHd1dHNzdHZ3eXp8fX6AgYOEhYaIi42Qj4+NjIqIhoSBfnt3c29rZmJcV1RQTE9SVlpeYmdscXd9g4mQlp2iqK60usHIz9fSy8S9tq6mnpWNhn93b2ZeVU1FPTQsJBsTGiQuNz9IUFhhaXF6goqTm6OrtLzEzdbg6uXd1czEvLOro5uSioJ5cWhfVUxCOTAmHRMXHygwOEFJUVpibHV+h5Gao6y1vsfQ2eLr6eHYz8a9tKuimZCHfnVtZFtSSUE4LycfFxkiKzQ8RU5WX2hweYGKkpujq7O7w8vT2+Pj2tLJwbmwqKCXj4d/d29nX1dPRj42LiYeHiYuNz9HT1dfZ293f4ePl5+nr7e/x87W3t/Xz8e/t6+ooJiQiIB4cWlhWVJKQjszKyQiKTE5QUlQWGBnb3d+ho6VnaSss7vCytHZ3NTMxb22rqafl5CJgXpya2NcVU1GPzcwKSUtNDxDSlJZYGhvdn6FjJOboqmwt77FzdTY0cnCu7StpZ6XkImCe3RtZl9YUUpDPDUuKTA3PkVMU1phaG92fYSLkpifpq20usHIz9TNxr+5squknZeQiYJ8dW5oYVpUTUdAOTMtNDpBSE5VW2Jpb3Z8g4mQlp2jqrC2vcPK0MrDvbawqaOdlpCJg312cGpjXVdRSkQ+ODI3PURKUFZdY2lvdnyCiI6UmqCnrbO5v8XLxsC6tK6oopyWkIqDfXdxa2VfWlROSEI8Njk/RUtRV11jaW91e4GHjZOZn6Wrsbe9w8jFv7q0rqiinJaQioR+eHJsZ2FbVU9JQz03OkBGS1FXXWNpb3V7gIaMkpiepKmvtbvBx8W/ubOuqKKclpCLhX95c21oYlxWUEtFPzk6QEZMUVddY2ludHqAhouRl52iqK60ub/Fxb+5s66oopyXkYuFgHp0bmljXVdSTEZBOztARkxSV11jaG50eX+Fi5CWnKGnrbK4vsPEvrmzraiinJeRi4aAe3VvamReWVNOSEI9O0FGTFJXXWJobnN5f4SKj5WaoKarsba8wcS+ubOtqKKdl5GMhoF7dnBrZWBaVE9JRD48QUdMUlddYmhtc3h+g4mOlJmfpKqvtbrAw764s62oop2XkoyHgXx2cWxmYVtWUEtGQDxCR0xSV11iaG1yeH2DiI6TmJ6jqa6zub7DvbiyraiinZeSjYeCfXdybWdiXFdSTEdCPUJHTVJXXWJnbXJ3fYKHjZKXnaKnrbK3vMK9uLKtqKKdmJKNiIN9eHNtaGNeWFNOSUM+QkhNUlddYmdscnd8gYeMkZacoaarsLa7wLy3sq2nop2Yk42Ig355dG5pZF9aVU9KRUBDSE1SWF1iZ2xxd3yBhouQlZqgpaqvtLm+vLeyrKeinZiTjomEfnl0b2plYFtWUUxHQkNITlNYXWJnbHF2e4CFio+UmZ6jqa6zuL27trGsp6KdmJOOiYR/enVwa2ZhXFdSTUhDRElOU1hdYmdscXZ7gIWKj5OYnaKnrLG2u7u2saynop2Yk46JhYB7dnFsZ2JdWFRPSkVESU5TWF1iZ2xwdXp/hImOk5ecoaarsLS5urWxrKeinZiUj4qFgHt3cm1oY19aVVBLR0VKT1NYXWJna3B1en+DiI2Slpugpamus7i6tbCrp6KdmJSPioWBfHdzbmlkYFtWUk1IRkpPVFhdYmdrcHV5foOHjJGVmp+jqK2xtrm0sKumop2YlI+LhoF9eHNvamVhXFhTTkpGS09UWV1iZ2twdHl+goeLkJSZnqKnq7C0ubSvq6ainZiUj4uGgn15dHBrZmJdWVRQS0dLUFRZXWJma3B0eX2ChouPlJidoaWqrrO3s6+qpqGdmZSQi4eCfnl1cGxnY19aVlFNSExQVVleYmZrb3R4fYGFio6Tl5ugpKmtsbazrqqmoZ2YlJCLh4N+enZxbWhkYFtXU05KTFFVWV5iZ2tvdHh8gYWJjZKWmp+jp6ywtLKuqqWhnZiUkIyHg396dnJuaWVhXVhUUExNUVZaXmJna29zeHyAhIiNkZWZnqKmqq6ysq2ppaGdmJSQjIiDf3t3c29qZmJeWlZRTU5SVlpeYmdrb3N3e4CEiIyQlJicoaWprbGxramloZyYlJCMiISAfHhzb2tnY19bV1NPTlJWWl9jZ2tvc3d7f4OHi4+Tl5ufo6err7CsqKSgnJiUkIyIhIB8eHRwbGhkYFxYVFBPU1dbX2Nna29zd3t/g4eKjpKWmp6ipqqusKyopKCcmJSQjIiFgX15dXFtaWVhXlpWUlBTV1tfY2drb3N2en6ChoqOkZWZnaGlqayvq6ekoJyYlJCMiYWBfXl2cm5qZmNfW1dTUFRYXF9jZ2tvcnZ6foKFiY2RlJicoKOnq66rp6OfnJiUkI2JhYF+enZyb2tnZGBcWVVRVVhcYGRna29ydnp9gYWIjJCTl5ueoqapraqmo5+bmJSQjYmFgn56d3NwbGhlYV5aVlNVWV1gZGdrb3J2eX2BhIiLj5OWmp2hpKirqaain5uXlJCNiYaCf3t3dHBtaWZiX1tYVFZaXWFkaGtvcnZ5fYCEh4uOkpWZnKCjpqqppaKem5eUkI2JhoJ/fHh1cW5qZ2NgXVlWV1peYWRoa29ydnl8gIOHio2RlJibnqKlqKiloZ6al5SQjYmGg398eXVyb2toZWFeW1dXW15hZWhrb3J1eXx/g4aJjZCTl5qdoKSnp6ShnZqXk5CNioaDgHx5dnNvbGlmYl9cWVhbX2JlaGxvcnV5fH+ChomMj5KWmZyfoqano6CdmpaTkI2KhoOAfXp3c3BtamdkYF1aWVxfYmZpbG9ydXh8f4KAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgA==",
    "bgm": "UklGRqxYAQBXQVZFZm10IBAAAAABAAEAESsAABErAAABAAgAZGF0YYhYAQCAgICAgYKDgoOEhIWGh4eIiImJiYmJiYiIh5WVlZSUk3p4dXNwbWpnZGFeW1dUUU5LSEVpaGdmZmY8PDw8PT5AQkRGSUtPUlZaXmJmoqessbe8h4uQlJicoKOmqKqsrq+wsbGxsevn49/b15aRjIeCfHdxbGZhXFdSTUhEQDxzb2xpZmQoJiUjIyIiIiIjIyQmJykqLC4wbXJ3fIGGU1hdYWZrb3N3e36BhYeKjI6QksnKy8vLy5aVlZSTkpGPjoyKiYeFg4KAfnytqaSgnJhhXltYVVJQTUtKSEdFRURDQ0NDdXV2d3d4SElLTE5PUVJUVVdYWltcXV5fYJGVmJqdoHN1d3l7fH1/f4CBgYGBgYGBgICsrKuqqad5eHd2dXRzcnFwb25ubW1sbGxsl5WSkI6NYF9eXVxbWlpaWVlZWlpaW1tcXYeHiImKi4tkZGVmZ2hoaWlqampqampqammQkpSWl5iadHV2d3h4eXl5eXl5eXl5eHh4nJubmpmZmHNzcnJycXFxcXBwcXFxcXJyc5aUkpGPjo1paGdnZmVlZGRkY2NjY2NjZGSFhYaGhoeHZmZnZ2doaGhoaGhoaGhoZ2dmZomLjY6QkXJzdHV2d3h5ent7fHx9fX19fn6fn5+fn59+fX19fX19fX19fX19fX19fX5+nZuZl5WTcG9tbGppZ2ZlY2JhYF9fXl1dXH18fHt7e1lZWVhYWFhYWFhXV1dXV1dXV1d5fH6AgoRlZ2lrbW9xc3V2eHl7fH5/gIKDpaanqKmqiouLjI2Njo+PkJCQkZGSkpKTk7OxrqyqqIWCgH58enh2dHJwbmxqaGZkY2GAf317enhWVFNSUE9OTUtKSUhHRkVERENCZGVnaWtsTU9RU1RWWFpcXmBiZGZoamxub5OVlpianH1/gIKEhoiJi42OkJGTlZaYmZq8u7q5uLeUk5KRkI6NjIqJiIaFg4KAf318m5qYlpWTcG5ta2loZmRiYV9dW1pYVlRTUXFycnN0dFRUVVZWV1hZWVpbXF1dXl9gYWKEhYaHiImKamtsbW5wcXJzdHZ3eHp7fH5/oaCfn56dnHp5eHh3dnV1dHNycnFwcG9ubo6NjYyLi4poZ2dmZWRkY2JhYWBfXl5dXFt8fX+AgYOEZGVnaGlrbG1ucHFyc3R2d3h5m5ydnqChooGCg4SFhoeIiYqLjI2Oj4+QkZKysa+urauJh4aEg4KAf318e3l4dnV0cnFvj46Ni4qIZmRjYmBfXlxbWlhXVlRTUlFPTnBxcnNzdFRVVldYWVpbXF1eX2BhYmNkZWaIiYqLjI1tbm9wcnN0dX+AgYKDhIWGh4iJqqmop6algoGAf359fHt6eXh3dnV0cnFwb4+OjYyLimhnZmVkYmFgX15dXFtaWVhXVlV2d3h5entbXF1eYGFiY2RlZmdoaWprbG1ukZKTlJWWdnd4eXp7fH1+f4GCg4SFhoeIiaqpqKempYOCgX9+fXx7enl4d3Z1dHNycW+Qj46Mi4poZ2ZlZGNiYWBeXVxbWllYV1ZVdnd4eXp7W1xdXl9gYWJkZWZnaGlqa2xtbpCSk5SVlnZ3eHl6e3x9fn+AgYKDhYaHiImrqainpqWDgoGAf359e3p5eHd2dXRzcnFwkI+OjYyLiWdmZWRjYmFgX15dW1pZWFdWVXZ3eHl6e3xcXV5fYGFiY2RlZmhpamtsbW6QkZKTlJaXdnh5ent8fX5/gIGCg4SFhoiJq6qpqKalpIKBgH9+fXx7enh3dnV0c3JxcG+Pjo2Mi4pnZmVkY2JhYF9eXVxbWllXVlVUdnd5ent8XF1eX2BhYmNkZWZnaGlqbG1ub5GSk5SVlnZ3eHl6fH1+f4CBgoOEhYaHiImqqainpqWCgYB/fn18e3p5eHd2dHNycXBvj46NjIuKaGdmZGNiYWBfXl1cW1pZWFdWVXZ3eHl6e1tcXV9gYWJjZGVmZ2hpamtsbW+RkpOUlZZ2d3h5ent8fX6AgYKDhIWGh4iJqqmop6alg4GAf359fHt6eXh3dnV0c3Jwb5COjYyLimhnZmVkY2JgX15dXFtaWVhXVlV2d3h5entbXF1eX2BhY2RlZmdoaWprbG1ukZKTlJWWdnd4eXp7fH1+f4CBg4SFhoeIiaqpqKempYOCgYB/fXx7enl4d3Z1dHNycXCQj46NjIpoZ2ZlZGNiYWBfXlxbWllYV1ZVdnd4eXp7fFxdXl9gYWJjZGZnaGlqa2xtbpCRkpSVlpd3eHl6e3x9fn+AgYKDhIWHiImrqqmnpqWkgoGAf359fHt5eHd2dXRzcnFwkI+OjYyLimdmZWRjYmFgX15dXFtaWFdWVXV3eHl6e3xcXV5fYGFiY2RlZmdoamtsbW5vkZKTlJWWdnd4ent8fX5/gIGCg4SFhoeIiaqpqKempYKBgH9+fXx7enl4d3V0c3JxcG+Pjo2Mi4poZ2VkY2JhYF9eXVxbWllYV1VUdnd4eXt8W11eX2BhYmNkZWZnaGlqa2xub5GSk5SVlnZ3eHl6e3x+f4CBgoOEhYaHiImqqainpqWCgYB/fn18e3p5eHd2dXRycXBvj46NjIuKaGdmZWRjYWBfXl1cW1pZWFdWVXZ3eHl6e1tcXV5fYWJjZGVmZ2hpamtsbW6RkpOUlZZ2d3h5ent8fX5/gIKDhIWGh4iJqqmop6alg4KBgH9+fXx7enl3dnV0c3JxcI+OjYuKiWloZ2ZlZGNiYWBfXl1cW1pZWFd0dXZ3eHldX2BhYmNkZWZnaWprbG1ub3ByjY6PkJGSeXp8fX5/gIGCg4SGh4iJiouMjaalpKOhoJ+HhoWEg4KBgH9+fXx7enl4d3aKiYiHhoSDbm1sa2poZ2ZlZGNiYWBfXl1cbm9wcXJzdGNkZmdoaWprbG1vcHFyc3R1doiJiouMjY5/gIGDhIWGh4iJioyNjo+QkZKhoJ+enZuajIuKiYiHhoWEg4KBgH9+fXx7eoSDgoGAfnNycXBvbm1sa2ppaGdmZWRjYmFqa2xtbm9oaWpsbW5vcHFyc3R2d3h5ent8g4SFhoeIhIWGh4mKi4yNjo+QkZOUlZaXmJuamZiXlpKQj46NjIuKiYiHhoWEg4KBgH9/fn18e3p4d3Z1dHNycXBvbm1samloZ2ZlZmdoaWprbG1ub3BxcnN0dXd4eXp7fH1+f4CBgoOEhYeIiYqLjI2Oj5CRkpOUlZeYmZqamZeWlZSTkpGQj46NjIuKiYiGhYSDgoGAf359fHt6eXh2dXRzcnFwb25tbGtqaWhmZWVmZ2hqa2xtbm9wcXJzdHV2d3h6e3x9fn+AgYKDhIWGh4iJi4yNjo+QkZKTlJWWl5iZmpmYl5aVk5KRkI+OjYyLiomIh4aFg4KBgH9+fXx7enl4d3Z1dHJxcG9ubWxramloZ2ZlZmdoaWprbG5vcHFyc3R1dnd4eXp7fH5/gIGCg4SFhoeIiYqLjI6PkJGSk5SVlpeYmZqZmJeWlZSTkpGPjo2Mi4qJiIeGhYSDgoF/fn18e3p5eHd2dXRzcnFvbm1sa2ppaGdmZWZnaGlqa2xtbm9xcnN0dXZ3eHl6e3x9fn+AgoOEhYaHiImKi4yNjo+QkpOUlZaXmJmamZiXlpWUk5KRkI+OjIuKiYiHhoWEg4KBgH9+fXt6eXh3dnV0c3JxcG9ubWtqaWhnZmVnaWttb2VlZWVlZWVlZWVlZmZmZmaSlJaYmmZmZmZmZmZoaWprbG1ub3CztLW2t3d4eXl4d3Z1dHNycXBvbm2sqqmop2dmZWRjYmFgXl1cW1pZWFeUk5KRkFFQT05NTEtKSUhHR0hJSkyJiouMjVJTVFVXWFlaW1xdXl9hYmOen6ChomlrbG1ub3BxcnN1dnd4eXq0tba2tXx7enl3dnV0c3JxcG9ubWyioaCfnWZlZGNiYWBfXl1cW1pZWFeLioiHhlFQT05NTEtMTU5QUVJTVFWJiouMjVxdXl9gYWJkZWZnaGlqa2yfoKGio6R0dXZ3eXp7fH1+f4CBgoGwrq2sq6p6eXh3dnV0c3JxcG9ubWyYl5aVlJNlZGNhYF9eXVxbWllYV1aBgH9+fXtPUFFTVFVWV1hZWltdXl9gi4yNjo9naGlqa2xtbm9wcnN0dXZ3oKGio6R+f4CBgoOEhoeGhYSDgoGApaSjoqB5eHd2dXRzcnFwb25tbGtqjoyLiolkY2JhYF9eXVxbWllYV1ZVdnd4eXpZWltcXV5fYWJjZGVmZ2hpjI2Oj5BwcXJzdHV2d3h5ent9fn+AoqOkpaaGh4iJiYiHhoWDgoGAf359nZybmpl3dnV0cnFwb25tbGtqaWhnh4aFhINgX15dXFtaWVhXVlVVVldYent8fn9eYGFiY2RlZmdoaWprbG1ukZKTlJWWdnd4eXp7fH1+f4GCg4SFp6ipqqqph4aFhIOCgX9+fXx7enl4mJeWlZSTcW9ubWxramloZ2ZlZGNigoGAf358WllYV1ZVVVZXWFlaW1xdXoCCg4SFZWZnaGlqa2xtbm9wcXJ0dZeYmZqbe3x9fn+AgYKDhYaHiImJiKinpqWkgoGAf359e3p5eHd2dXRzcpKRkI+Oa2ppaGdmZWRjYmFgX15dW3x7enh3VVRVV1hZWltcXV5fYGFiY4aHiImKamtsbW5vcHFyc3R1dnh5epydnp+ggIGCg4SFhoiJioiHhoWEg6OioaCffXx7enh3dnV0c3JxcG9ubY2Mi4qJZmVkY2JhYF9eXVxbWllXVnd1dnd5WFlbXF1eX2BhYmNkZWZnaIuMjY6PkHBxcnN0dXZ3eHl6fH1+f6Gio6SlpoaHiImJiIeGhIOCgYB/fp6dnJuamXd2dHNycXBvbm1sa2ppaIiHhoWEg2BfXl1cW1pZWFdWVVVWV1h6e31+f19gYWJjZGVmZ2hpamtsbW+RkpOUlXV2d3h5ent8fX6AgYKDhIWnqKmqqoiHhoWEg4GAf359fHt6eXiYl5aVlHJwb25tbGtqaWhnZmVkY2KCgYB+fVtaWVhXVlVVVldYWVpbXF2AgYKDhGRlZmdoaWprbG1ub3Bxc3SWl5iZmnp7fH1+f4CBg4SFhoeIiYmpqKempYOCgYB/fXx7enl4d3Z1dHOTkpGQj2xramloZ2ZlZGNiYWBfXlx9fHp5eFZVVFZXWFlaW1xdXl9gYWKFhoeIiWlqa2xtbm9wcXJzdHV3eHmbnJ2en6CAgYKDhIWHiImJiIeGhYSko6KhoJ99fHt5eHd2dXRzcnFwb26OjYyLiolmZWRjYmFgX15dXFtaWFdWdnV3eHlYWltcXV5fYGFiY2RlZmdoi4yNjo9vcHFyc3R1dnd4ent8fX5/oaKjpKWFhoeIiYmIhoWEg4KBgH9+np2cm5p4d3V0c3JxcG9ubWxramloiIeGhYNhYF9eXVxbWllYV1VUVVZXeXt8fX5eX2BhYmNkZWZnaGlqa2xukJGSk5R0dXZ3eHl6e3x+f4CBgoOEpqeoqaqJiIeGhYSCgYB/fn18e3p5mZiXlpVycXBvbm1sa2ppaGdmZWRjg4KBf35cW1pZWFdWVVVWV1hZWltcf4CBgoNjZGVmZ2hpamtsbW5vcXJzlZaXmJmaent8fX5/gIKDhIWGh4iJqqmop6alg4KBgH59fHt6eXh3dnV0lJOSkZCPbGtqaWhnZmVkY2JhYF5dfn17enl4VlVVVldYWVpbXF1eX2BhYoWGh4iJaWprbG1ub3BxcnN1dnd4eZucnZ6ff4CBgoOEhoeIiYmIh4aFhKSjoqGgfn17enl4d3Z1dHNycXBvbo6NjIuKZ2ZlZGNiYWBfXl1cWllYV3d2dnd4WFlaW1xdXl9gYWJjZGVmZ4qLjI2Obm9wcXJzdHV2d3l6e3x9fqChoqOkhIWGh4mKiYeGhYSDgoGAf5+enZybeXd2dXRzcnFwb25tbGtqaYmIh4aEYmFgX15dXFtaWVhWVVRVVnh6e3x9XV5fYGFiY2RlZmdoaWpsbY+QkZKTlHR1dnd4eXp7fX5/gIGCg6Wmp6ipq4mIh4aEg4KBgH9+fXx7epqZmJeWlXJxcG9ubWxramloZ2ZlY4SDgYB/flxbWllYV1ZVVVZXWFlaW1x/gIGCg2NkZWZnaGlqa2xtbnBxcnOVlpeYmXl6e3x9foCBgoOEhYaHiImqqainpoSDgoB/fn18e3p5eHd2dXSUk5KRkG1sa2ppaGdmZWRjYmFfXl19fHt6eVdWVVVWV1hZWltcXV5fYGGEhYaHiGhpamtsbW5vcHFydHV2d3iam5ydnn5/gIGChIWGh4iJiYiHhoWlpKOioX9+fHt6eXh3dnV0c3JxcG+Pjo2Mi2hnZmVkY2JhYF9eXVtaWVh4d3Z2d1dYWVpbXF1eX2BhY2RlZmeIiYqLjI1vcHFyc3R2d3h5ent8fX6en6ChoqOGh4mKi4yLiomIh4aFhIOdnJuamZh7enl4d3Z1dHNycXBvbm2GhYSDgYBmZWRjYmFgX15dXFtaWVpbdHV2d3hiY2RlZmdoamtsbW5vcHFziYqLjI15ent9fn+AgYKDhIWHiImKnp+goaKRkI+OjYyLiomIh4aFhIOCkpGQj418e3p5eHd2dXRzcXBvbm1senl4d3ZmZWRjYmFgX15fYGFiY2RldHV2d3hsbW5wcXJzdHV2d3h6e3x9iYqLjI2EhYaHiImKi42Oj5CRkpOUnp6dnJqRkI+OjYyLiomIh4aFhIOCh4aFhIN8e3p5eHd2dXRzcnFwb25tcG9ubWxnZmVjZGVmZ2hpamttbm9wc3R1dnd3eHl6e3x9fn+BgoOEhYaHiYqLjI2Oj5CRkpOUlZaXmJqamZiXlZSTkpGQj46NjIuKiYiHhoSDgoGAf359fHt6eXh3dnRzcnFwb25tbGtqaWhnZmVmZ2hpamxtbm9wcXJzdHV2d3h5ent9fn+AgYKDhIWGh4iJiouNjo+QkZKTlJWWl5iZmpmYl5aVlJORkI+OjYyLiomIh4aFhIOBgH9+fXx7enl4d3Z1dHNycG9ubWxramloZ2ZlZmdoaWprbG1ucHFyc3R1dnd4eXp7fH1+gIGCg4SFhoeIiYqLjI2Oj5GSk5SVlpeYmZqZmJeWlZSTkpGQj42Mi4qJiIeGhYSDgoGAf318e3p5eHd2dXRzcnFwb25sa2ppaGdmZWZnaGlqa2xtbm9wcXJ0dXZ3eHl6e3x9fn+AgYKEhYaHiImKi4yNjo+QkZKUlZaXmJmamZiXlpWUk5KRkI+OjYyLiYiHhoWEg4KBgH9+fXx7eXh3dnV0c3JxcG9ubWxraWhnZmVlZ2hpamtsbW5vcHFyc3R1d3h5ent8fX5/gIGCg4SFhoiJiouMjY6PkJGSk5SVlpiZhp6onZOhln6IgIB1laOCo5i5n5qNgWt0eXGAgGFcRl1TQZd7mpdhQFxOSypPSDdHTkYpcIJ9jThFVVZGXF5gYWRPQouasZWQbVN6hFZjcl1ZYX95q72comd3hINcin5rXX2DbYSxpKy3dmlfW3FaaXdjUG1aX6SfnY9UYmddYVJpcGJtVlStirGmdHBYS2peQ1tGSl46YZeRjpdVOlNXQlZSRD5JWz5be36On2FVXmNgXFZrUnNfdZeWuJyybnBzkHJ+hZSCd5KXx8LGtX6MenSQjG9pbYZgZV+klJSHbE9kb1tXaG1WYkVOYI6HkHNITVleT0dhZEhNZGR6hJKBgWBRTWpuVmJodGBjbIeeh4pXZl5vYWh0Ym51d3pqmp2flndofGVlc3Z+iHBshHytqbSpj299iHl4iYB3hXWApKShl21nd4B6bG1lYWRtWFp9i5CIalFUSmBhX0xFQlRRRnBseXZCTEtcS01VTlZWX12JlZODlGVrc3Rwb3l1boR1iqGYr5t+eoZ3doB2gouBg4yTm5ydn4B9dnNvhWyAdoJydGyUh5CQe2xrZnRpb2FpZnRflIWJjGBvY21uZF9ga1VmVVl8cneBZ19YWmZcYWdiW1pYa4yCgXtjYmtubGtvaXhuan+Lj6CcmHp0fIF7gIiOjYmHiLWvtqKHiISNiYaKfot3dIV1npqZm3h4b2hiZWVtZGFkYliBgoJ3XFRiXVtfWllPYE9XbIGCd39jXWBrWmhnZGdybG+MhpGVd2lubXRqbnp1bnx7fZeWl5dydXh1gHp3d4mJiYOOpaitnoODe3h7dn2GgXh0eqKhopN8dntrdWpvb3RxamVxjo6FimpbY19fXVdQV1pTUUprb3l0W1laX1lXY2NdZmhmiIiGiJJuZnR2dW19dHp6e3SkpqangoaFfIWHg42Ai46LjrGnpamDgIWDd399dHxwcHNuloyWk25sbHBkbGxoaGJrX4CLgIN9Y11nZlpgWF1ZWFZVent+flZaYGBjX2NoZGJda2WHgoKQaGlvcnJqcm1xdXNvfJSamJZ6eIN9goeBhoWCiZGpsKeqjoSGgoF/f4CDf3d8gJSdl5p5c3BscXJuZm1nYWZggIB9gV1XXFVbWVhTVU9QUnFwfH5/WV5aY2RiX2ZkamRojZCKkmxucHFvcnhwcHN6d3aal5mZeYN/eYV7foN+f4aBhKekqaJ9g3yDfHt4fH16fnaclJyZeXN1cm9va3JtbmZoZoeMiIRkZl9iWmFcXl1cU1RRdHd0eVpaWlhhWGBfXV1lYoWCjIaMbGtsbW50dXh5e3h+m6Cbo4F+f4CBgoOEhoeIiYmpqKemhIOCgYB/fn17enl4d5eWlZRycXBvbm1samloZ2aGhYSDgmBfXl1cWllYV1ZVVHd4eXpaW1xdXl9gYWJjZGVmiYqLjGxtbm9wcXJzdHV2d3mbnJ2efn+AgYKDhIWGh4mKqqmop4SDgoGAf359fHt6eXeYl5WUcnFwb25tbGtqaWdmZYaEg4JgX15dXFtaWVhWVVR2d3h6e1pcXV5fYGFiY2RlZoiKi4xsbW5vcHFyc3R1dnd4m5ydnn5/gIGCg4SFhoeIiYmpqKemg4KBgH9+fXx7enl4mJeWlXJxcG9ubWxramloZ2aGhYSDYF9eXVxbWllYV1ZVVXd4eXpaW1xdXmBhYmNkZWaIiYqLjGxtbnBxcnN0dXZ3eJqbnJ59foCBgoOEhYaHiImJqainpoSDgoB/fn18e3p5eHeXlpWUcnFvbm1sa2ppaGdmhoWEg4JfXl1cW1pZWFdWVVV3eHl6WltcXV5fYGFjZGVmZ4mKi4xsbW5vcHFydHV2d3h5m5ydnn5/gIGChIWGh4iJiamop6aEg4KBgH9+fHt6eXh3l5aVlHJxcG9ubGtqaWhnZmWFhIOCYF9eXVtaWVhXVlVUd3h5entbXF1eX2BhYmNkZWeJiouMbG1ub3BxcnN0dXd4eZucnZ5+f4CBgoOEhYaIiYmIqaimpYOCgYB/fn18e3p4d5iWlZSTcXBvbm1sa2poZ2ZlhYSDgmBfXl1cW1pYV1ZVVFV4eXp7W1xdXl9gYWJjZGVmZ4qLjI1tbm9wcXJzdHV2d3ibnJ2efn+AgYKDhIWGh4iJiamop6aDgoGAf359fHt6eXh3l5aVlHFwb25tbGtqaWhnZoaFhIKBX15dXFtaWVhXVlRVd3h5elpbXF5fYGFiY2RlZmeJioyNbG5vcHFyc3R1dnd4eZudnp9/gIGCg4SFhoeIiYmpqKemhIOBgH9+fXx7enl4d5eWlZRxcG9ubWxramloZ2ZlhYSDgl9eXVxbWllYV1ZVVXd4eXp7W1xdXl9gYmNkZWZniYqLjGxtbm9wcnN0dXZ3eHmbnJ2efn+AgYOEhYaHiImJiKinpqWDgoGAfn18e3p5eHeXlpWUk3Fwb21sa2ppaGdmZYWEg4JgX11cW1pZWFdWVVVWeHl6e1tcXV5fYGFiY2RmZ2iKi4yNbW5vcHFyc3R2d3h5m5ydnn5/gIGCg4SGh4iJiYiop6alg4KBgH9+fXx6eXh3dpaVlJNxcG9ubWxqaWhnZmWFhIOCgV9eXVxbWVhXVlVUVXh5entbXF1eX2BhYmNkZWZniouMjW1ub3BxcnN0dXZ3eHqcnZ6ff4CBgoOEhYaHiIqJqainpqSCgYB/fn18e3p5eHeWlZSTcnFwb25tbGtqaWhnZoOCgYBhYF9eXVxbWllYV1d1dnd4eV5fYGFiZGVmZ2hpaoaHiIlwcXJzdHV3eHl6e3x9mJmam4OEhYaHiIqLjI2Ojo2joqGgh4aFhIOCgYB/fn18kZCPjo12dXRzcnFwb25tbGt+fXx7ZmVkY2JhYF9eXVxcXXFyc3RjZGVmZ2hqa2xtbm9wgoOEhXZ3eHl6e3x+f4CBgpKTlJWIiYqLjI2Oj5GSk5OSnp2cm42Mi4qJiIeGhYSDgoGLiomIfHp5eHd2dXRzcnFweXh3dnVqaWhnZmVkY2JhYWJsbW5vaGlqa2xtbm9xcnN0dX1+f4B7fH1+f4CBgoSFhoeIjo+QkY6PkJGSk5SVlpiYl5mYl5aVkZCPjo2Mi4qJiIeGhoWEg4GAf359fHt6eXh3dnV0cnFwb25tbGtqaWhnZmVmZ2hpamtsbm9wcXJzdHV2d3h5ent8fX+AgYKDhIWGh4iJiouMjY+QkZKTlJWWl5iZmpmYl5aVlJOSkY+OjYyLiomIh4aFhIOCgYB+fXx7enl4d3Z1dHNycXBubWxramloZ2ZlZmdoaWprbG1ub3Byc3R1dnd4eXp7fH1+f4CBg4SFhoeIiYqLjI2Oj5CRk5SVlpeYmZqZmJeWlZSTkpGQj46Ni4qJiIeGhYSDgoGAf359e3p5eHd2dXRzcnFwb25tbGppaGdmZWZnaGlqa2xtbm9wcXJzdHZ3eHl6e3x9fn+AgYKDhIaHiImKi4yNjo+QkZKTlJWXmJmampiXlpWUk5KRkI+OjYyLiomHhoWEg4KBgH9+fXx7enl3dnV0c3JxcG9ubWxramlnZmVlZmdpamtsbW5vcHFyc3R1dnd4ent8fX5/gIGCg4SFhoeIiouMjY6PkJGSk5SVlpeYmpqZmJeWlJOSkZCPjo2Mi4qJiIeGhIOCgYB/fn18e3p5eHd2dXNycXBvbm1sa2ppaGdmZmhqZGRkZGRlZWVlf4GDZWVlZWVlZWVlZZqcnmZmZmZmZ2hpaq2vsG9wcXJzdHV3eHm6ubh3dnRzcnFwb26trKtqaWhnZmVkY2Jhn56dXVxbWllYV1ZVkZCPUVBPTk1MS0pJSIOEhUpLTE1OT1FSU4+QkVdYWVtcXV5fYGGdnp9mZ2hpamtsbW6pqqtzdHV2d3h6e3x9trW0e3p5eHd2dXRzqainpm5tbGtqaWhnZpuamGJhX15dXFtaWY2Mi4pUU1JRUE9OTUx/gIFOT1BRUlNVVleLjI2OXF1fYGFiY2RlmJmaamtsbW5vcHFzdKWmp3h5ent8fn+AgbKxsIB/fn18e3p4d3ako6JycXBvbm1sa2qXlpRmZWRjYmFgX15diIeGWVhXVlVUU1JRe3t8UlNUVVZYWVpbXIeIiWBiY2RlZmdoaZSVlm5vcHFyc3R1d3ihoqN8fX5/gYKDhIWtrayEg4KBgH9+fXx7oJ+ed3Z1dHNycXBvk5GQa2ppaGdmZWRiYYSDgl1cW1pZWFdWVXd2d3lXWFlbXF1eX2CDhIVkZmdoaWprbG2PkJGTcnN1dnd4eXp7nZ6ff4CBgoOEhoeIiaupqIaFhIOCgYB/fp6dnHl4d3Z1dHNycXCQj45samloZ2ZlZGODgoFfXl1cWllYV1ZVdnd4WFlaW1xdXl9ggoOEZGVmZ2lqa2xtbpCRknJzdHV2d3l6e52en3+AgYKDhIWGh4mrqqmGhYSDgoGAf36enZx6eXd2dXRzcnFwkI+ObGtqaWdmZWRjg4KBX15dXFtaWVhWVXZ2d1dYWVpcXV5fYIKDhIVlZmdoaWpsbW6QkZJyc3R1dnd4eXqdnp+ggIGCg4SFhoeIq6qph4aEg4KBgH9+fZ2cm3l4d3Z1c3JxcJCPjmxramloZ2ZlY2KDgYBeXVxbWllYV1Z2dndXWFlaW1xdXmBhg4SFZWZnaGlqa2xtkJGScnN0dXZ3eHl6e56foICBgoOEhYaHiKqqqYeGhYSDgoB/fn2dnJt5eHd2dXRzcnGRkI9sa2ppaGdmZWRjg4KBXl1cW1pZWFdWdnZ3V1hZWltcXV5fYIOEhWVmZ2hpamtsbY+RkpNydHV2d3h5enudnp9/gIGChIWGh4iqqqmohoWEg4KBgH9+np2ceXh3dnV0c3JxkZCPjmtqaWhnZmVkY4OCgV9eXVtaWVhXVlV2d3hYWVpbXF1eX2CCg4VkZWdoaWprbG1ukJGScnN0dXd4eXp7nZ6ff4CBgoOEhYaIiauqqYaFhIOCgYB/fp6dnHp4d3Z1dHNycXCQj45sa2poZ2ZlZGODgoFfXl1cW1pYV1ZVdXZ4V1haW1xdXl9ggoOEZGVmZ2hpa2xtbpCRknJzdHV2d3h5e52en3+AgYKDhIWGh4irqqmHhYSDgoGAf36enZybeXh3dXRzcnFwkI+ObGtqaWhnZmRjhIKBgF5dXFtaWVhXVnZ2d1dYWVpbXF5fYGGDhIVlZmdoaWprbG6QkZJyc3R1dnd4eXp7np+ggIGCg4SFhoeIqqqph4aFhIOBgH9+fZ2cm3l4d3Z1dHNxcJGPjmxramloZ2ZlZGODgoFeXVxbWllYV1Z2dndXWFlaW1xdXl9gg4SFZWZnaGlqa2xtkJGScnN0dXZ3eHl6e52eoH+AgYOEhYaHiKqqqYeGhYSDgoGAfn2enZt5eHd2dXRzcnGRkI+Oa2ppaGdmZWRjg4KBX11cW1pZWFdWdnZ3eFhZWltcXV5fYIOEhWRmZ2hpamtsbW6QkZJyc3R2d3h5enudnp9/gIGCg4SGh4iJq6qohoWEg4KBgH9+np2ceXh3dnV0c3JxcJCPjmxqaWhnZmVkY4OCgV9eXVxbWVhXVlV1d3hXWVpbXF1eX2CCg4RkZWZnaWprbG1ukJGScnN0dXZ3eHp7nZ6ff4CBgoOEhYaHiKuqqYaFhIOCgYB/fp6dnHp5eHZ1dHNycXCQj45sa2ppaGZlZGODgoGAXl1cW1pZWFdVdnZ3V1hZWltdXl9ggoOEhWVmZ2hpamttbpCRknJzdHV2d3h5ep2en6CAgYKDhIWGh4irqqmHhoWDgoGAf359nZybeXh3dnV0cnFwkI+ObGtqaWhnZmVkYoOCgF5dXFtaWVhXVnZ2d1dYWVpbXF1eYGGDhIVlZmdoaWprbG2QkZJyc3R1dnd4eXp7nZ+gf4GCg4SFhoeIqqqph4aFhIOCgX9+fZ2cm3l4d3Z1dHNycZGQj2xramloZ2ZlZGODgoFeXVxbWllYV1Z2dndXWFlaW1xdXl9gg4SFZWZnaGlqa2xtj5CSk3J0dXZ3eHl6e52en3+AgYKDhYaHiKqrqaiGhYSDgoGAf36enZx5eHd2dXRzcnFwkI+Oa2ppaGdmZWRjg4KBX15dW1pZWFdWVXZ3eFhZWltcXV5fYIKDhGRlZmhpamtsbW6QkZJyc3R1dnh5enudnp9/gIGCg4SFhoiJq6qphoWEg4KBgH9+np2cenh3dnV0c3JxcJCPjmxramlnZmVkY4OCgV9eXVxbWllXVlV1dndXWFlbXF1eX2CCg4RkZWZnaGlqbG1ukJGScnN0dXZ3eHl6nZ6foICBgoOEhYaHiKuqqYeGhIOCgYB/fp6dnJt5eHd2dHNycXCQj45sa2ppaGdmZGNig4GAXl1cW1pZWFdWdnZ3V1hZWltcXl9gYYOEhWVmaGlqa2xtbo+QkXN0dXZ3eHl7fH2cnZ6BgoSFhoeIiYqoqKeJiIeGhYSDgoGAm5mYfHt6eXh3dnV0jYyLcG9ubWxramloZ39+fGNiYWBfXlxbWnFxclxdXl9gYWJjZWZ9fn9qa2xub3BxcnOKi4x4eXp7fH1+f4GCl5iZhoeIiYuMjY6Po6OioY2Mi4qJiIeGhZaVlIGAf359fHt6eYiHhoV0c3JxcG9ubWx6eXhoZ2ZlZGNiYWBsbG1uYmNkZWZnaGlreHl6b3BxcnN1dnd4eYWGh35/gIGCg4SFhpGSk4uMjY6PkJKTlJWenZyTkpGQj46NjIuRkI+HhoWDgoGAf359goGAeXh3dnV0c3JxdXRzbWxramloZ2ZlZGdoaWZoaWprbG1ub3N0dXR1dnd4eXp8fX6AgYKCg4WGh4iJiouMjY6PkZKTlJWWl5iZmpmYl5aVlJOSkZCPjoyLiomIh4aFhIOCgYB/fnx7enl4d3Z1dHNycXBvbmxramloZ2ZlZmdoaWprbG1ub3BxcnR1dnd4eXp7fH1+f4CBgoOFhoeIiYqLjI2Oj5CRkpOVlpeYmZqZmJeWlZSTkpGQj46NjIuJiIeGhYSDgoGAf359fHt6eHd2dXRzcnFwb25tbGtqaGdmZWVmaGlqa2xtbm9wcXJzdHV2eHl6e3x9fn+AgYKDhIWGiImKi4yNjo+QkZKTlJWWl5mampmYl5WUk5KRkI+OjYyLiomIh4WEg4KBgH9+fXx7enl4d3V0c3JxcG9ubWxramloZ2ZlZmdoaWpsbW5vcHFyc3R1dnd4eXp8fX5/gIGCg4SFhoeIiYqMjY6PkJGSk5SVlpeYmZqZmJeWlZSSkZCPjo2Mi4qJiIeGhYSDgYB/fn18e3p5eHd2dXRzcXBvbm1sa2ppaGdmZWZnaGlqa2xtb3BxcnN0dXZ3eHl6e3x9foCBgoOEhYaHiImKi4yNjpCRkpOUlZaXmJmgpauwta+ytLa4ubq6urq5uNjY19arp6KemJONh4F7dG1mopyWkEhCPDYxLCciHRkVEg9PT09PDxESFRcaHSEkKS0ydnuAhYtRV11iaG1zeH2Ch4zO0tbZn6Kkpqiqq6ysrKysq+Xh3tmZlZCLh4J9d3JtaGNelJCLhkdDPzw4NTIwLiwqKWFgYGAmJycoKSssLjAyNDY5dXp+g1BUWV5iZ2tvc3d6foG7vcDCjY+RkpOTlJSUlJOTx8bFw8KLiYeFg4F/fXt4dnSloZ2aYl9bWFVTUE5MSkhHRXd2dXVCQkJDQ0RFRkdJSkxNgIKDhVZYWlxdX2FiZGVmZ5mcnqGjdnh6fH5/gIGCg4ODsbGxsYKCgYB/fn17enl3dnWgnp2cbm1ramloaGdmZmZmZY6MiolcW1pZWFhXV1dXV1eBgoKDWltcXV5fYGFiY2RmZ5CRkpNsbW1ub29vcHBwcHBwmJqbnHd4eXp6e3t7fHx8fKGgoJ+feXh4d3Z2dXRzcnJxlJOTkm5tbW1sbGxsbGxtbW2OjYyKZ2ZlZGRjY2JiYmJiYoODg4RjY2NkZGVlZmdnaGiKi4uLa2trbGxsbGxsbGxsa46QkZNzdHV3eHl5ent7fHx9np+fn35+fn5+fX19fXx8fJ2cnJycenp6eXl5eXl5eXl5mZeVk3BubWtqaWdmZWRjYmGBgIB/XV1cXFxbW1tbWlpaWnt7e3taWlpbW1tbW1tbW1t+gIKEhmdpamxucHJzdXZ4eZydn6CAgYKDhIWGh4eIiYmKrKytrYyNjY2Ojo6Ojo+Pj46tq6mnhIKAfnx6eHZ0cnBujoyKiWZkYmFfXlxbWVhXVVR0c3JxTk1MTEtKSUhHR0ZFRmlqbG1OT1FTVVZYWlxdX2GEhoiKi2xucHFzdXd4enx+f6KkpqeIiYuMjo+RkpSVlpiYuLe3tpOSkZCPjo2MiomIh4WlpKKhfn18enl3dXRycW9ujYyKiIdkYmFfXVxaWFdVU1J0dXV2VVZWV1dYWFlaWltcXH5/gIFgYWJjZGVlZmdoaWprjo+QkXFyc3R2d3h5e3x9fp6enZx6eXl4d3d2dXV0c3NykpKRkW9ubW1sbGtqamloaGeIh4aGZGNiYmFgYF9eXV1cfoCBgoRkZWZoaWprbW5vcHGUlZaXd3h5ent8fX5/gIGCg6Wmp6iIiYmKi4yNjo+QkJGQsK+trImIh4WEg4GAf318epqZmJZ0cnFvbm1ramlnZmVjg4KBf11bWllXVlVUUlFQTk9xcnN0U1RVVldYWVpbXF1egIGCg4RkZWZnaGlqa2xtbm+Sk5SVdX+AgYKDhIWGh4iJiamop6aDgoGAf359fHt6eXh3l5aVlHFwb25tbGtqaWhnZoaFhIOCX15dXFtaWVhXVlVVd3h5elpbXF1eYGFiY2RlZmeJiouMbG1ub3Fyc3R1dnd4eZucnZ9+f4GCg4SFhoeIiYmpqKemhIOCgX9+fXx7enl4d5eWlZRycW9ubWxramloZ2ZlhYSDgmBeXVxbWllYV1ZVVXd4eXp7W1xdXl9gYWJkZWZniYqLjGxtbm9wcXJ0dXZ3eHmbnJ2efn+AgYKDhYaHiImJiKinpqWDgoGAf359e3p5eHeXlpWUcnFwb25ta2ppaGdmZYWEg4JgX15dW1pZWFdWVVRVeHl6e1tcXV5fYGFiY2RlZomKi4yNbW5vcHFyc3R1dnh5m5ydnn5/gIGCg4SFhoiJioipqKalg4KBgH9+fXx7enh3dpeVlJNxcG9ubWxramlnZmWFhIOCgV9eXVxbWllXVlVUVXd5entbXF1eX2BhYmNkZWZniouMjW1ub3BxcnN0dXZ3eHmcnZ6ff4CBgoOEhYaHiImJqainpoOCgYB/fn18e3p5eHeXlpWUcXBvbm1sa2ppaGdmZIWEg4FfXl1cW1pZWFdWVVV3eHl6e1tcXV9gYWJjZGVmZ4mKi41sbW9wcXJzdHV2d3h5m52en36AgYKDhIWGh4iJiYiop6alg4GAf359fHt6eXh3l5aVlJNwb25tbGtqaWhnZmWFhIOCX15dXFtaWVhXVlVVVnh5entbXF1eX2BhY2RlZmdoiouMjW1ub3Bxc3R1dnd4eZucnZ5+f4CBg4SFhoeIiYmIqKempYOCgYB/fXx7enl4d3aWlZSTcXBvbmxramloZ2ZlhYSDgoFfXlxbWllYV1ZVVFZ4eXp7W1xdXl9gYWJjZGZnaIqLjI1tbm9wcXJzdHV3eHl6nJ2en3+AgYKDhIWHiImJiKmnpqWDgoGAf359fHt5eHd2lpWUk3Fwb25tbGtpaGdmZWSEg4KBX15dXFtaWFdWVVRVeHl6e3xcXV5fYGFiY2RlZmeKi4yNbW5vcHFyc3R1dnd4epydnp9/gIGCg4SFhoeIiYmIqKempYKBgH9+fXx7enl4d5eWlZOScG9ubWxramloZ2VkhYOCgV9eXVxbWllYV1VUVVZ4eXt8W11eX2BhYmNkZWZnaIuMjY5ub3BxcnN0dXZ3eHmcnZ6ff4CBgoOEhYaHiImJiKinpqWCgYB/fn18e3p5eHd2lpWUk3Bvbm1sa2ppaGdmZYWEg4KBXl1cW1pZWFdWVVVWeHl6e1tcXV5fYWJjZGVmZ2iKi4yNbW5vcXJzdHV2d3h5epydn6B/gIKDhIWGh4iJiYiop6alpIKBgH9+fXx7enl3dpWUk5JxcG9ubWxramloZ2Zlg4GAf2BfXl1cW1pZWFdXWHZ3eHl6X2BhYmNkZWZnaWprh4iJinByc3R1dnd4eXp8fX6YmZqbg4SGh4iJiouMjY6NjKOhoJ+HhoWEg4KBgH9+fXyRkI6NjHZ1dHNycXBvbm1sa359e3plZGNiYWBfXl1cXF1ecXJzdGNkZmdoaWprbG1vcHGDhIWGdnd5ent8fX5/gIGDk5SVloiJioyNjo+QkZKTkpGenZuajIuKiYiHhoWEg4KBgIuKiYd7enl4d3Z1dHNycXB5eHd2dGppaGdmZWRjYmFhY2xtbm9oaWpsbW5vcHFyc3R2fX5/gHt8fX6AgYKDhIWGh4mPkJGSjo+QkZOUlZaXmJiXmZiXlpSQj46NjIuKiYiHhoWGhYSDgH9+fXx7enl4d3Z1dHNycXBvbm1samloZ2ZlZmdoaWprbG1ub3BxcnN0dXd4eXp7fH1+f4CBgoOEhYeIiYqLjI2Oj5CRkpOUlZeYmZqamZeWlZSTkpGQj46NjIuKiYiGhYSDgoGAf359fHt6eXh2dXRzcnFwb25tbGtqaWhmZWVmZ2hqa2xtbm9wcXJzdHV2d3h6e3x9fn+AgYKDhIWGh4iJi4yNjo+QkZKTlJWWl5iZmpmYl5aVk5KRkI+OjYyLiomIh4aFg4KBgH9+fXx7enl4d3Z1dHJxcG9ubWxramloZ2ZlZmdoaWprbG5vcHFyc3R1dnd4eXp7fH5/gIGCg4SFhoeIiYqLjI6PkJGSk5SVlpeYmZqZmJeWlZSTkpGPjo2Mi4qJiIeGhYSDgoF/fn18e3p5eHd2dXRzcnFvbm1sa2ppaGdmZWZnaGlqa2xtbm9xcnN0dXZ3eHl6e3x9fn+AgoOEhYaHiImKi4yNjo+QkpOUlZaXmJmamZiXlpWUk5KRkI+OjIuKiYiHhoWEg4KBgH9+fXt6eXh3dnV0c3JxcG9ubWtqaWhnZmVnaWttb2VlZWVlZWVlZWVlZmZmZmaSlJaYmmZmZmZmZmZoaWprbG1ub3CztLW2t3d4eXl4d3Z1dHNycXBvbm2sqqmop2dmZWRjYmFgXl1cW1pZWFeUk5KRkFFQT05NTEtKSUhHR0hJSkyJiouMjVJTVFVXWFlaW1xdXl9hYmOen6ChomlrbG1ub3BxcnN1dnd4eXq0tba2tXx7enl3dnV0c3JxcG9ubWyioaCfnWZlZGNiYWBfXl1cW1pZWFeLioiHhlFQT05NTEtMTU5QUVJTVFWJiouMjVxdXl9gYWJkZWZnaGlqa2yfoKGio6R0dXZ3eXp7fH1+f4CBgoGwrq2sq6p6eXh3dnV0c3JxcG9ubWyYl5aVlJNlZGNhYF9eXVxbWllYV1aBgH9+fXtPUFFTVFVWV1hZWltdXl9gi4yNjo9naGlqa2xtbm9wcnN0dXZ3oKGio6R+f4CBgoOEhoeGhYSDgoGApaSjoqB5eHd2dXRzcnFwb25tbGtqjoyLiolkY2JhYF9eXVxbWllYV1ZVdnd4eXpZWltcXV5fYWJjZGVmZ2hpjI2Oj5BwcXJzdHV2d3h5ent9fn+AoqOkpaaGh4iJiYiHhoWDgoGAf359nZybmpl3dnV0cnFwb25tbGtqaWhnh4aFhINgX15dXFtaWVhXVlVVVldYent8fn9eYGFiY2RlZmdoaWprbG1ukZKTlJWWdnd4eXp7fH1+f4GCg4SFp6ipqqqph4aFhIOCgX9+fXx7enl4mJeWlZSTcW9ubWxramloZ2ZlZGNigoGAf358WllYV1ZVVVZXWFlaW1xdXoCCg4SFZWZnaGlqa2xtbm9wcXJ0dZeYmZqbe3x9fn+AgYKDhYaHiImJiKinpqWkgoGAf359e3p5eHd2dXRzcpKRkI+Oa2ppaGdmZWRjYmFgX15dW3x7enh3VVRVV1hZWltcXV5fYGFiY4aHiImKamtsbW5vcHFyc3R1dnh5epydnp+ggIGCg4SFhoiJioiHhoWEg6OioaCffXx7enh3dnV0c3JxcG9ubY2Mi4qJZmVkY2JhYF9eXVxbWllXVnd1dnd5WFlbXF1eX2BhYmNkZWZnaIuMjY6PkHBxcnN0dXZ3eHl6fH1+f6Gio6SlpoaHiImJiIeGhIOCgYB/fp6dnJuamXd2dHNycXBvbm1sa2ppaIiHhoWEg2BfXl1cW1pZWFdWVVVWV1h6e31+f19gYWJjZGVmZ2hpamtsbW+RkpOUlXV2d3h5ent8fX6AgYKDhIWnqKmqqoiHhoWEg4GAf359fHt6eXiYl5aVlHJwb25tbGtqaWhnZmVkY2KCgYB+fVtaWVhXVlVVVldYWVpbXF2AgYKDhGRlZmdoaWprbG1ub3Bxc3SWl5iZmnp7fH1+f4CBg4SFhoeIiYmpqKempYOCgYB/fXx7enl4d3Z1dHOTkpGQj2xramloZ2ZlZGNiYWBfXlx9fHp5eFZVVFZXWFlaW1xdXl9gYWKFhoeIiWlqa2xtbm9wcXJzdHV3eHmbnJ2en6CAgYKDhIWHiImJiIeGhYSko6KhoJ99fHt5eHd2dXRzcnFwb26OjYyLiolmZWRjYmFgX15dXFtaWFdWdnV3eHlYWltcXV5fYGFiY2RlZmdoi4yNjo9vcHFyc3R1dnd4ent8fX5/oaKjpKWFhoeIiYmIhoWEg4KBgH9+np2cm5p4d3V0c3JxcG9ubWxramloiIeGhYNhYF9eXVxbWllYV1VUVVZXeXt8fX5eX2BhYmNkZWZnaGlqa2xukJGSk5R0dXZ3eHl6e3x+f4CBgoOEpqeoqaqJiIeGhYSCgYB/fn18e3p5mZiXlpVycXBvbm1sa2ppaGdmZWRjg4KBf35cW1pZWFdWVVVWV1hZWltcf4CBgoNjZGVmZ2hpamtsbW5vcXJzlZaXmJmaent8fX5/gIKDhIWGh4iJqqmop6alg4KBgH59fHt6eXh3dnV0lJOSkZCPbGtqaWhnZmVkY2JhYF5dfn17enl4VlVVVldYWVpbXF1eX2BhYoWGh4iJaWprbG1ub3BxcnN1dnd4eZucnZ6ff4CBgoOEhoeIiYmIh4aFhKSjoqGgfn17enl4d3Z1dHNycXBvbo6NjIuKZ2ZlZGNiYWBfXl1cWllYV3d2dnd4WFlaW1xdXl9gYWJjZGVmZ4qLjI2Obm9wcXJzdHV2d3l6e3x9fqChoqOkhIWGh4mKiYeGhYSDgoGAf5+enZybeXd2dXRzcnFwb25tbGtqaYmIh4aEYmFgX15dXFtaWVhWVVRVVnh6e3x9XV5fYGFiY2RlZmdoaWpsbY+QkZKTlHR1dnd4eXp7fX5/gIGCg6Wmp6ipq4mIh4aEg4KBgH9+fXx7epqZmJeWlXJxcG9ubWxramloZ2ZlY4SDgYB/flxbWllYV1ZVVVZXWFlaW1x/gIGCg2NkZWZnaGlqa2xtbnBxcnOVlpeYmXl6e3x9foCBgoOEhYaHiImqqainpoSDgoB/fn18e3p5eHd2dXSUk5KRkG1sa2ppaGdmZWRjYmFfXl19fHt6eVdWVVVWV1hZWltcXV5fYGGEhYaHiGhpamtsbW5vcHFydHV2d3iam5ydnn5/gIGChIWGh4iJiYiHhoWlpKOioX9+fHt6eXh3dnV0c3JxcG+Pjo2Mi2hnZmVkY2JhYF9eXVtaWVh4d3Z2d1dYWVpbXF1eX2BhY2RlZmeIiYqLjI1vcHFyc3R2d3h5ent8fX6en6ChoqOGh4mKi4yLiomIh4aFhIOdnJuamZh7enl4d3Z1dHNycXBvbm2GhYSDgYBmZWRjYmFgX15dXFtaWVpbdHV2d3hiY2RlZmdoamtsbW5vcHFziYqLjI15ent9fn+AgYKDhIWHiImKnp+goaKRkI+OjYyLiomIh4aFhIOCkpGQj418e3p5eHd2dXRzcXBvbm1senl4d3ZmZWRjYmFgX15fYGFiY2RldHV2d3hsbW5wcXJzdHV2d3h6e3x9iYqLjI2EhYaHiImKi42Oj5CRkpOUnp6dnJqRkI+OjYyLiomIh4aFhIOCh4aFhIN8e3p5eHd2dXRzcnFwb25tcG9ubWxnZmVjZGVmZ2hpamttbm9wc3R1dnd3eHl6e3x9fn+BgoOEhYaHiYqLjI2Oj5CRkpOUlZaXmJqamZiXlZSTkpGQj46NjIuKiYiHhoSDgoGAf359fHt6eXh3dnRzcnFwb25tbGtqaWhnZmVmZ2hpamxtbm9wcXJzdHV2d3h5ent9fn+AgYKDhIWGh4iJiouNjo+QkZKTlJWWl5iZmpmYl5aVlJORkI+OjYyLiomIh4aFhIOBgH9+fXx7enl4d3Z1dHNycG9ubWxramloZ2ZlZmdoaWprbG1ucHFyc3R1dnd4eXp7fH1+gIGCg4SFhoeIiYqLjI2Oj5GSk5SVlpeYmZqZmJeWlZSTkpGQj42Mi4qJiIeGhYSDgoGAf318e3p5eHd2dXRzcnFwb25sa2ppaGdmZWZnaGlqa2xtbm9wcXJ0dXZ3eHl6e3x9fn+AgYKEhYaHiImKi4yNjo+QkZKUlZaXmJmamZiXlpWUk5KRkI+OjYyLiYiHhoWEg4KBgH9+fXx7eXh3dnV0c3JxcG9ubWxraWhnZmVlZ2hpamtsbW5vcHFyc3R1d3h5ent8fX5/gIGCg4SFhoiJiouMjY6PkJGSk5SVlpiZhp6onZOron6IgIB1laOCo5iXe3RlgWt0eXG1tpqWgpxTQVQ5WFVhQFxOSypPSDdHTkYpcIJ9jXiFVVZGXF5gYWRPQktacVVRbVN6hJWisJyYn395bX9eZGd3hINcin5rXX2DbYSxpKy3sqVfW3FaaXdjUG1aX2lkYlRUYmddm42kqpynVlRzUHdsdHBYS2peQ1tGSl46YZeRjpeNclNXQlZSRD5JWz5bREdXaGFVXmOWkoyhiKlfdWJhg2d9bnBzkHJ+hZSCd5KXx8LGtbG/enSQjG9pbYZgZV9xYmFVbE9kb42Jmp6Hk0VOYF1WX0JITVleT0dhZEhNZGR6hJKBgY9RTWpuVmJodGBjbFlwWVxXZl5vjpWij5uid3pqbXFyaXdofGVlc3Z+iHBshKetqbSpum99iHl4iYB3hXWAenp3bW1nd4CjlpaNio2VWFpVYmhgalFUSmBhX0xFQlRRbXBseXZpc0tcS01VTlZWX11kb21eb2Vrc5mVlJ2Zk6l1in10i3d+eoZ3doB2gouBg4y2m5ydn6OgdnNvhWyAdoJydGxzZm9ve2xrh5WKkIOLiHRfc2Noa2BvY21uZF9ga1VmVVl8cneBiIBYWmZcYWdiW1pYa2thYFljYmtujY2QipmQan9pbn96d3p0fIF7gIiOjYmHiLWvtqKoqYSNiYaKfot3dIV1fXl4enh4b2iDhoaOhYNkYlhfYGFWXFRiXVtfWllPYE9XbIGCd3+EXWBrWmhnZGdybG9rZHB0d2lubZWLj5uWj3x7fXZ1dnVydXh1gHp3d4mJiYOvpaitnqSDe3h7dn2GgXh0eoGAgXJ8dntrlouQkJWSamVxbW1jaWpbY19fXVdQV1pTUWtrb3l0fVlaX1lXY2NdZmhmZ2ZlZnFuZnSXlo6elZt6e3SDhYWGgoaFfIWHg42Ai46Lr7GnpamlgIWDd399dHxwcHNudWp1cm5sbJGFjY2JiWJrX15qX2JcY11nZlpgWF1ZWFZ2ent+fndaYGBjX2NoZGJda2VmYGFvaGlvk5OMlI6SlnNvfHJ5d3V6eIN9goeBhoWCibKpsKeqr6WGgoF/f4CDf3d8gHN7dXl5c3CNkpOPh46IYWZgXl9bYF1XXFVbWVhTVU9QdHFwfH5/el5aY2RiX2ZkamRoa29pcGxucJOQk5mRkZV6d3Z5dnh4eYN/eYV7foN+f4aBpaekqaKeg3yDfHt4fH16fnZ6c3t4eXN1cpGQjJOOj2ZoZmVqZ2NkZl9iWmFcXl1cU1RydHd0eXtaWlhhWGBfXV1lYmRhamVrbGtsj4+Vl5mae3h+en96goF+f4CBgoOEhoeIiaqpqKempYOCgYB/fnx7enl4d3Z1dHNycXCQj46NjItoZ2ZlZGNiYWBfXl1cW1pZWFdWdnd4eXp7W1xdXl9gYWJjZWZnaGlqa2xtbpCRkpOUlXV2d3h5ent8fX+AgYKDhIWGh4iqqainpqWDgoF/fn18e3p5eHd2dXRzcnFwkI+OjYyLaWhnZmVkY2JhYF9eXVxbWVhXVnd3eHl7fFtcXV5fYGFjZGVmZ2hpamtsbW6QkZKTlJV1dnd4eXp7fH1+f4CBgoOEhYaHqamop6algoGAf359fHt6eXh3dnV0c3JxcJCPjo2Mi4poZ2ZlZGNiYWBfXl1cW1pZWFd4eHl6e3x9XV5fYGFiY2RlZmdoaWprbG1ukJGSk5SVlnV2d3h5ent8fX5/gIGCg4SFhqiop6alpKOBgH9+fXx7enl4d3Z1dHNycXBvkI+OjYyLaWhnZmVkY2JhYF9eXVxbWllYV3h5ent8fV1eX2BhYmNkZWZnaGlpamtsbW6QkZKTlJV1dnd4eXp7fH1+f3+AgYKDhIWGqKempaSjgYB/fn18e3p5eHd2dXRzcnFxcJCPjo2Mi2loZ2ZlZGNiYWFgX15dXFtaWVh5ent8fX5dXl9gYWJjZGVmZ2hoaWprbG1ukJGSk5SVdXZ2d3h5ent8fX5/gIGCgoOEhaempaSjo4B/f359fHt6eXh3dnV0c3NycXCQj46NjItpaGhnZmVkY2JhYF9eXl1cW1pZeXp7fH1+Xl5fYGFiY2RlZmdoaGlqa2xtbpCRkpOUlXR1dnd4eXp7e3x9fn+AgYKDg4SmpqWko6KAf359fHx7enl4d3Z1dHRzcnFwkI+Pjo2MamloZ2ZlZGRjYmFgX15dXVxbWnp7fHx9fn9fYGFhYmNkZWZnaGhpamtsbW6QkZKSk5SVdXZ2d3h5ent8fX1+f4CBgoODpqWkpKOioX9+fXx7e3p5eHd2dXR0c3JxcJCQj46NjItpaGhnZmVkY2JiYWBfXl1cXFt7e3x9fn9/X2BhYmNjZGVmZ2hoaWprbG1ubpGRkpOUlXR1dnd4eXl6e3x9fn5/gIGCg4OlpKOioaF/fn18e3p5eXh3dnV0dHNycXBvkI+OjYyMamloZ2ZlZWRjYmFhYF9eXVxcW3x8fX5/gF9gYWJjZGRlZmdoaWlqa2xtbW6QkZKTlJR0dXZ2d3h5ent7fH1+f3+AgYKDpKSjoqGgfn19fHt6eXl4d3Z1dHRzcnFwcJCPjo6NjGppaGhnZmVkZGNiYWBgX15dXFx8fX5/f4BgYWFiY2RlZWZnaGlpamtsbW1ukJGSkpOUdHR1dnd4eHl6e3x8fX5/f4CBgqSjoqGhoH59fHx7enl5eHd2dnV0dHNycXGPjo6NjItsa2ppaWhnZmZlZGRjYmFhYF9fe3t8fX1+Y2NkZWZnaGhpamtsbG1ub3BxcY2Njo+PkHd4eXl6e3x9fn5/gIGCgoOEhYaenp2cm5uagoGAgH9+fn18e3t6eXl4d3Z2ioqJiIeGhnBwb25tbWxra2ppaWhnZ2ZlZHd3d3h5eXppamprbG1ubm9wcXJyc3R1dXaHiImJiouLfX1+f4CAgYKDhISFhoeHiImKmJiXl5aVlIeGhYSEg4KCgYCAf35+fXx8e3qFhIOCgoF2dXR0c3JycXBwb25ubWxsa2pqcnNzdHV1bm9wcHFyc3R0dXZ3d3h5enp7fIODhIWFhoGCg4SEhYaHh4iJioqLjI2Njo+TkpGQkI+Li4qJiYiHh4aFhYSDg4KBgYB/gH9+fn18e3p6eXh4d3Z2dXR0c3JycXBvb25vcHBxcnNzdHV1dnd3eHl5ent7fH1+fn+AgIGCgoOEhIWGhoeIiImKiouMjI2Ojo+QkJCPjo6NjIyLioqJiIiHhoaFhISDgoKBgIB/fn59fHx7enp5eHh3dnZ1dHRzcnJxcHBvcHBxcnJzdHR1dnZ3eHh5enp7e3x9fX5/f4CBgYKDg4SFhYaHh4iJiYqKi4yMjY6Oj5CPj46NjYyLi4qJiYiHh4aFhYSEg4KCgYCAf35+fXx8e3t6eXl4d3d2dXV0dHNycnFwcHBxcXJzc3R1dXZ2d3h4eXp6e3x8fX1+f3+AgYGCgoOEhIWGhoeHiImJioqLjIyNjo6Pj46NjYyMi4qKiYiIh4eGhYWEg4OCgoGAgH9/fn19fHx7enp5eHh3d3Z1dXR0c3JycXFxcXJyc3R0dXV2d3d4eXl6ent8fH19fn9/gICBgoKDg4SFhYaGh4eIiYmKiouMjI2Njo6OjYyMi4uKiYmIiIeGhoWFhIODgoKBgIB/f35+fXx8e3t6eXl4eHd3dnV1dHRzc3JxcnR1d25ubm1tbGxra2tqaoyNj5BoZ2dmZmVlZWRkY2Nipaamp2VmZ2doaGlqamtrbG2ura2sa2pqaWloaGdnZmZlpKSjoqJiYmFhYGBfX15eXV2amZmYWllZWFhXV1ZWVVVUVJCRkZJWVldYWFlZWltbXFxdmZmammBhYWJiY2NkZWVmZqGhoqJpamprbGxtbW5ub3Bwqamop29ubm1tbGxra2pqaWmfn56dZmZmZWVkZGNjYmJhlpWVlJReXl1dXFxbW1paWVmMjY2OW1tcXF1dXl9fYGBhYZSVlZZkZWVmZmdoaGlpamprnJ2dnm5ub29wcHFycnNzdKSko6OicnJxcXBwb29vbm5tm5qamWtqamlpaGhoZ2dmZmWSkZCQY2NiYmFhYGBfX19eXomJiopgYGFiYmNjZGRlZWaQkZGSaWlqamtrbGxtbW5ub5iYmZlycnNzdHR1dXZ2d3d4n56enXZ2dXV0dHNzc3JycZaWlZWUb25ubW1tbGxra2pqjo2NjGhnZ2dmZmVlZGRkY2OFhoaHZWVmZmdnaGhpaWpqa42NjY5tbm5vb29wcHFxcnKUlJWVdXV1dnZ3d3h4eXl5epubmpp4eHd3dnZ2dXV0dHNzlJOTknFwcG9vbm5tbW1sbIyMjIuLaWloaGdnZmZmZWVkhYaGhmZmZ2dnaGhpaWpqa2uNjY6ObW5ubm9vcHBxcXJycpSUlZV0dXV2dnd3d3h4eXmbmpqZmXd3d3Z2dXV0dHRzc5STk5JxcHBvb25ubm1tbGxsjIyMi2ppaWhoZ2dnZmZlZWWGh4eHZ2dnaGhpaWpqamtrjY2Ojm1ubm5vb3BwcHFxcnKUlJSVdHR1dXZ2dnd3eHh4eZqZmZl3d3Z2dXV1dHRzc3OTk5OSknBwb29vbm5tbW1sbI2MjIxqamlpaGhoZ2dnZmZlh4eIiGdnaGhpaWlqamtra2yNjo6Obm5ub29vcHBxcXFyk5SUlJV0dHV1dXZ2d3d3eHiZmZiYdnZ2dXV1dHRzc3NycpOSkpJwcG9vb25ubm1tbWxsjYyMjGpqaWlpaGhoZ2dnZoeIiIhoaGhpaWlqampra2xsjY6Ojm5ubm9vb3BwcHFxcXKTlJSUdHR0dXV1dnZ2d3d3mZiYmJd2dXV1dHR0c3NzcnKTkpKScHBvb29ubm5tbW1sbI2NjIxqampqaWlpaGhoZ2dniImJiWhpaWlqampra2tsbI6Ojo9ubm5vb29wcHBxcXFxk5OUlHNzdHR0dXV1dnZ2d3eYl5eXdXV1dHR0c3NzcnJyk5KSkpFwb29vb25ubm1tbWyNjY2Ma2tqamppaWlpaGhoZ4mJiYppaWlqampra2tsbGxsjo6Pj25ub29vb3BwcHFxcZOTk5SUc3N0dHR0dXV1dXZ2l5eWlnV0dHR0c3NzcnJycXGSkpKRcHBvb29ubm5ubW1tbI2NjY1ra2tqamppaWlpaGiJioqKaWpqampra2tsbGxsbY6Oj49ubm9vb29wcHBwcXFxk5OTk3Jzc3N0dHR0dXV1dZaWlpaVdHRzc3NzcnJycnFxkpKRkXBwb29vbm5ubm1tbW2OjY2NbGtra2tqampqaWlpaYqLi4tqamtra2tsbGxsbW2Oj4+Pbm5vb29vb3BwcHBxcZKTk5NycnNzc3NzdHR0dHV1lpWVlXNzc3NycnJycnFxcZKSkZGRb29vb29ubm5ubW1tjo6OjWxsbGtra2tqampqammLi4uMa2tra2tsbGxsbW1tbY+Pj49ub29vb29wcHBwcHGSkpKTk3JycnJzc3Nzc3R0dJWVlZRzc3NycnJycXFxcXFwkZGRkW9vb29vbm5ubm5tbW2Ojo6ObGxsbGtra2trampqjIyMjGtra2xsbGxsbW1tbW2Pj4+Pbm9vb29vb3BwcHBwcZKSkpJxcnJycnJyc3Nzc3OUlJSUlHJycnJycXFxcXFwcJGRkZFvb29vb29ubm5ubm5tjo6Ojm1sbGxsbGxra2tra2uMjY2NbGxsbGxtbW1tbW1uj4+Pj5Bvb29vb29vcHBwcHCSkpKScXFxcXJycnJycnJzc5STk5NycnFxcXFxcXFwcHBwkZGRkW9vb29vb25ubm5ubo+Pjo5tbW1tbGxsbGxsbGxsjY2NjWxsbW1tbW1tbW5ubm6Pj5CQb29vb29vb29wcHBwkZGSkpJxcXFxcXFxcnJycnKTk5OTcXFxcXFxcHBwcHBwcJGRkZFvb29vb29vbm5ubm5uj4+Pj21tbW1tbW1tbGxsbI6Ojo5tbW1tbW1tbm5ubm5uj5CQkG9vb29vb29vb3BwcHCRkZGRcHBwcXFxcXFxcXFxkpKSkpJxcXBwcHBwcHBwcHCRkZGQb29vb29vb29ubm5ubo+Pj49ubm5tbW1tbW1tbW1tjo6Oj21tbm5ubm5ubm5ubpCQkJCQb29vb29vb29vb29wkZGRkXBwcHBwcHBwcHBwcXCSkpGRcHBwcHBwcHBwcG9vb5CQkJBvb29vb29vb29ubm6Qj4+Pbm5ubm5ubm5ubm5ubo+Pj49ubm5ubm5ubm5ubm9vkJCQkG9vb29vb29vb29vb5GRkZGRcHBwcHBwcHBwcHBwkZGRkXBwcG9vb29vb29vb2+QkJCQb29vb29vb29vb29vb5CQkJBubm5ubm5ubm5ubm6QkJCQkG5vb29vb29vb29vb4+Pj49wcHBwcHBwcHBwcHBwj4+Pj3FxcXFxcXFxcXFxcY6Ojo6OcnJycnJycnJycnJyjY2NjXJycnJycnNzc3Nzc3OMjIyMc3Nzc3Nzc3NzdHR0dIuLi4t0dHR0dHR0dHR0dHSKioqKinV1dXV1dXV1dXV1dYqKiYl2dnZ2dnZ2dnZ2dnZ2iYmJiXZ3d3d3d3d3d3d3d3eIiIiId3d3d3h4eHh4eHh4h4eHh3h4eHh4eHh4eXl5eXmGhoaGeXl5eXl5eXl5eXl6eoWFhYV6enp6enp6enp6enqFhISEhHt7e3t7e3t7e3t7e4SEhIR8fHx8fHx8fHx8fHx8g4ODg3x8fH19fX19fX19fX2CgoKCfX19fX19fn5+fn5+gYGBgYF+fn5+fn5+fn5/f3+AgICAf39/f39/f39/f39/gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICFjJOZn6arsaapq62vsLGxsbCvrauopaKempaRi4aAerWwq6agm5WQSUM/OjUxLSkmIyAeHBoZGBcXFxgZGhsdYGRobHB1eX5ESU5TWF1iZ2xxdXl+gYWIi46QkpSVltTU1NTU09LQkpCOjIqIhYOAfXp3dHFubGlnZWJhX11clJGOjIqIhoVLSkpKSktMTU5PUVNVV1pcXmFjZmlrbqiqrK6wsrO1f4CBgYGCgYGAf359e3l3dHJvbGllYl5ajIqIhoSCgH1HRUNBQD48Ozo4Nzc2NjY2NjY3ODk6PHBydHZ5e36BU1ZZXWFkaGxwdHh8gISIjJCTl5qeoaSn2NnZ2dnY2NenpqWkoqGfnZuYlpOQjYqHhIF9enZzb2yVkY6Kh4OAfU1KR0VCPz07ODY1MzEwLy4tLCsrKyoqVVhaXF9iZWdBREdLTlFUWFteYWVoa25xdHd6fX+ChIawsrS1t7i6u5WWl5iYmZmampqampmZmZiYl5aWlZSTt7SxrquopaJ7eXZzcW5samhmZGJgXl1bWlhXVlVUVFN0dHNzc3Nzc1FSUlJTU1NUVFVWVldXWFlZWlpbW1xcfoCChYeJi41tb3FydHV3eHl6e3x9fX5/f3+AgICAgIGioqGhoaGhoH9+fn59fXx8fHt7e3t6enp6enp6enp6e5uZl5aVk5KRbm1sbGtqaWloZ2dnZmZmZmVlZWVlZWWHh4eHh4eHiGZnZ2dnZ2dnZ2dnZ2dnZ2dmZmZlZWVkY4WHiImKi4yNbW5vb3BxcXJyc3N0dHR0dXV1dXV2dnaXl5eXl5eXl3Z2dnZ2dnZ3d3d3d3d4eHh5eXp6ent8fJ2cmpmYl5aVc3JxcHBvbm1tbGxramppaWloaGhnZ2eIh4eHh4eGhmVlZGRkZGRjY2NjYmJiYmFhYWBgX19eXoCBgoSFhoeIaGlqbG1ub29wcXJzdHR1dnd3eHl5enp7nJ2dnp6fn35/f4CAgIGBgYKCgoODg4SEhIWFhYaGhqempaOioJ+ee3p5d3Z1dHJxcG9ubWxqaWhnZmVkZGNigoGAgH9+fX1bWllZWFdXVlZVVFRTU1JSUVFQUE9PTm9xcnN1dnd5WVpcXV5gYWJjZWZnaWprbG5vcHFzdHV2mZqbnJ2en6CAgYKDhYaHiIiJiouMjY6PkJGRkpOUlbe2tbSzsrGvjYyLiomIh4aFg4KBgH9+fXx6eXh3dnVzk5KRkI+OjItpaGdlZGNiYWBeXVxbWllYV1VUU1JRUE9xcXJzc3R1VFVWVldYWFlaW1tcXV5eX2BhYWJjZGVlh4iJiouMjY1tbm9wcXp7fH1+fn+AgYKDhISFhoeIiYmqqaiop6alpIKBgIB/fn18e3t6eXh3dnV1dHNycXBwkI+OjY2Mi4poZ2ZlZWRjYmFgX19eXVxbWlpZWFdWVVR2d3h5eXp7fFxcXV5fYGFhYmNkZWZnZ2hpamtsbG1ukJGSk5SUlZZ2d3d4eXp7fH19fn+AgYKCg4SFhoeHiImqqqmop6alpIKCgYB/fn18fHt6eXh3d3Z1dHNycXFwb4+Ojo2Mi4poZ2ZmZWRjYmFhYF9eXVxbW1pZWFdWVlV2d3d4eXp7fFtcXV5fYGBhYmNkZWVmZ2hpamtrbG1ub5GSkpOUlZaXdnd4eXp7e3x9fn+AgYGCg4SFhoaHiImrqqmop6ampYOCgYB/fn59fHt6eXh4d3Z1dHNzcnFwb5CPjo2Mi4qKaGdmZWRjYmJhYF9eXV1cW1pZWFdXVlV2dnd4eXp7e1tcXV5eX2BhYmNkZGVmZ2hpaWprbG1ub5GRkpOUlZaWdnd4eXp6e3x9fn9/gIGCg4SEhYaHiImKqqmop6empYOCgYB/f359fHt6enl4d3Z1dHRzcnFwb5CPjo2MjIuKaGdmZWRkY2JhYF9eXl1cW1pZWVhXVlVUdnd4eXp6e3xcXV1eX2BhYmJjZGVmZ2hoaWprbG1tbpCRkpOUlZWWdnd4eHl6e3x9fn5/gIGCg4OEhYaHiIiJqqmpqKempaSCgYGAf359fHt7enl4d3Z2dXRzcnFwcJCPjo2NjIuKaGdmZWVkY2JhYGBfXl1cW1paWVhXVlVVdnd4eHl6e3xbXF1eX2BhYWJjZGVmZmdoaWprbGxtbm+RkpOTlJWWdnd3eHl6e3x8fX5/gIGBgoOEhYaHh4iJqqqpqKempaWCgoGAf359fXx7enl4d3d2dXRzcnJxcG+Pj46NjIuKiWdnZmVkY2JhYWBfXl1cXFtaWVhXVlZVdnd3eHl6e3xbXF1eX19gYWJjZGVlZmdoaWpqa2xtbm+RkpKTlJWWl3Z3eHl6e3t8fX5/gICBgoOEhYWGh4iJq6qpqKempqWDgoGAf35+fXx7enl5eHd2dXRzc3JxcG+Qj46NjIuLimhnZmVkY2NiYWBfXl1dXFtaWVhYV1ZVVHZ3eHl6e3tbXF1eXl9gYWJjY2RlZmdoaWlqa2xtbm6QkZKTlJWWlnZ3eHl5ent8fX5+f4CBgoOEhIWGh4iJiaqpqKinpqWkgoGAgH9+fXx7enp5eHd2dXV0c3JxcG+Qj46NjIyLimhnZmVkZGNiYWBfX15dXFtaWVlYV1ZVVHZ3eHl5ent8XFxdXl9gYWJiY2RlZmdnaGlqa2xtbW6QkZKTlJSVlnZ3eHh5ent8fX1+f4CBgoKDhIWGh4iJiqqpqKempaSkg4KCgYB/fn59fHt6enl4d3Z2dXRzcnJxjYyLioqJiGtqaWhnZ2ZlZGNjYmFgX19eXVxbW1pZWHJzdHV1dnd4X2BhYmNkZWZnZ2hpamtsbW5vcHBxcnN0jIyNjo+QkJF8fX5/gIGBgoOEhYaHiImKiouMjY6PkKSjoqGgn56diomIh4eGhYSDg4KBgH9/fn18e3t6eXh3h4aFhIODgoFwcG9ubWxsa2ppaGhnZmVkZGNiYWBgX2xsbW5vcHBxZmZnaGlqa2xtbm5vcHFyc3R1dnd3eHl6hYaHh4iJiouCg4SFhoeIiImKi4yNjo+QkZGSk5SVlpednJuamZiXkJCPjo2MjIuKiYiIh4aFhISDgoGAgH9+gYB/fn18fHt3dnV1dHNycXFwb25tbWxramlpaGdmZWVmZ2doaWprbGxtbm9wcXFyc3R1dnd3eHl6e3x8fX5/gIGBgoOEhYaHh4iJiouMjI2Oj5CRkpKTlJWWl5eYmZqamZiXlpWUlJOSkZCPj46NjIuKiYmIh4aFhISDgoGAf35+fXx7enl5eHd2dXRzc3JxcG9ubm1sa2ppaGhnZmVlZmdoaWpqa2xtbm9wcHFyc3R1dXZ3eHl6ent8fX5/gICBgoOEhYWGh4iJiouLjI2Oj5CQkZKTlJWWlpeYmZqamZiXlpaVlJOSkZCQj46NjIuLiomIh4aFhYSDgoGAgH9+fXx7enp5eHd2dXV0c3JxcG9vbm1sa2pqaWhnZmVlZmdoaWlqa2xtbm5vcHFyc3R0dXZ3eHl5ent8fX5+f4CBgoOEhIWGh4iJiYqLjI2Oj4+QkZKTlJSVlpeYmZqamZiXl5aVlJOSkpGQj46NjIyLiomIh4eGhYSDgoGBgH9+fXx8e3p5eHd2dnV0c3JxcXBvbm1sa2tqaWhnZmZlZmdnaGlqa2xtbW5vcHFycnN0dXZ3d3h5ent8fX1+f4CBgoKDhIWGh4iJi42PkZOGhoaGhoaFhYWFhYWFhISEgoB/sbGxsbKycnBvbm1sbGtqaWhoZ2ZlZGRjYqKhoJ+fnlxcW1pZWFhXVlVUVFNSUVBQT06Mi4qJiIdISEdGR0dISUpLTE1OT09QUVJTkJGSk5SUWVpbXF1eX19gYWJjZGVmZ2doaaWlpqeoqW9wcXJzdHV2d3d4eXp7fH1+fX20s7KxsLB3dnV1dHNycXFwb25tbWxramlpnp2cm5qZY2JhYWBfXl1cXFtaWVhYV1ZVVIiHhoWEg09OTUxMTE1OTk9QUVJTVFVWVleKi4yMjY5eXl9gYWJjZGVmZmdoaWprbG1unp+goKGidHV2dnd4eXp7fH1+fn+AgYKDg7Cvrq2sq319fHt6eXl4d3Z1dXRzcnFxcG+amZiXlpVpaWhnZmVlZGNiYWFgX15dXVxbg4KCgYB/flVUU1JRUVJTVFVVVldYWVpbXISEhYaHiIhjZGVlZmdoaWprbG1tbm9wcXKYmJmam5yceXp7fH19fn+AgYKDhIWFhoeIq6uqqainpoOCgoGAf359fXx7enl5eHd2dZaVlJOSkZBubm1sa2ppaGhnZmVkY2NiYWBfgH9+fXx7WVhYV1ZVVFVWV1hYWVpbXF1eXoCBgoOEhWRlZmdoaGlqa2xtbm5vcHFyc3OWlpeYmZp5ent8fX5+f4CBgoOEhIWGh4iJq6qpqKinhYSDgoGAgH9+fXx7enp5eHd2dZaVlJOSkm9vbm1sa2pqaWhnZmVkZGNiYWCBgH9+fXxaWVlYV1ZVVFVWV1dYWVpbXFxdf4CBgoOEY2RlZmdnaGlqa2xsbW5vcHFycpSVlpeYmXh5ent8fX1+f4CBgoKDhIWGh4iqqqqpqaiGhYSDgoGBgH9+fXx8e3p5eHd2l5aVlJOTcXBvbm1sa2tqaWhnZmZlZGNiYYKBgH9+fVtbWllYV1ZWVVVVVldYWVpbW1x+f4CBgoJiY2RlZWZnaGlqa2tsbW5vcHBxk5SVlpeYd3h5ent7fH1+f4CBgYKDhIWGhqmpqquqqaiGhYSDg4KBgH9+fX18e3p5eHiYl5aVlZSTcXBvbm1tbGtqaWhnZ2ZlZGNig4KBgH9/flxbWllYV1dWVVRVVldYWVlaW31+f4CBgYJiY2RkZWZnaGlpamtsbW5vb3CSk5SVlpeXd3h5enp7fH1+f3+AgYKDhIWFhqipqquqqYeGhYSEg4KBgH9/fn18e3p5eXiYl5aWlZRycXBvbm5tbGtqaWloZ2ZlZGNjg4KBgIB/XVxbWllZWFdWVVRVVldYWFlaW31+f3+AgWFiYmNkZWZnaGhpamtsbW1ub3CSk5SVlZZ2d3h4eXp7fH1+fn+AgYKDg4SFp6ipqquqiIeGhoWEg4KBgIB/fn18e3t6eZmYmJeWlXNycXBwb25tbGtqamloZ2ZlZWSEg4KCgYBeXVxbWlpZWFdWVVVVVlZXWFlafH1+fn+AYGFhYmNkZWZmZ2hpamtsbG1ub5GSk5SUlXV2d3d4eXp7fHx9fn+AgYKCg4Smp6ipqqqJiIeHhoWEg4KCgYB/fn18fHt6mpmZmJeWdHNycXFwb25tbGxramloZ2ZmZYWEg4OCgV9eXVxcW1pZWFdWVlVVVVZXWFl7fHx9fn+AX2BhYmNkZWVmZ2hpamprbG1ukJGSkpOUlXV1dnd4eXp7e3x9fn+AgIGCg6Wmp6ioqaqJiYiHhoWEg4OCgYB/fn59fHubm5qZmJeWdHNzcnFwb25tbWxramloaGdmZYWFhIOCgV9eXV1cW1pZWFhXVlVUVVZXWFl7e3x9fn9eX2BhYmNjZGVmZ2hpaWprbG1ukJGRkpOUdHR1dnd4eXl6e3x9fn9/gIGCg6Wmp6eoqYmKiYiHhoWFhIOCgYB/f359fHucm5qZmJd1dHRzcnFwb29ubWxramlpaGdmhoaFhIOCYF9fXl1cW1pZWVhXVlVUVVZXV3l6e3x9fl1eX2BhYmJjZGVmZ2doaWprbG2Pj5CRkpNyc3R1dnd4eHl6e3x9fX5/gIGCpKWlpqeoiIiJiYiHhoaFhIOCgYGAf359fJ2cm5qZmHZ2dXRzcnFwcG9ubWxra2ppaGeIh4aFhINhYGBfXl1cW1taWVhXVlVVVVZWeHl6e3x9XF1eX2BgYWJjZGVmZmdoaWpra46Oj5CRknFyc3R1dnZ3eHl6e3x8fX5/gIGjpKSlpqeoh4iJiYiIh4aFhIOCgoGAf359np2cm5qamXd2dXRzcnJxcG9ubWxsa2ppaImIh4aFhIRiYWBfXl1cXFtaWVhXV1ZVVFV3eHl6e3x8XF1eX19gYWJjZGRlZmdoaWpqjI2Oj5CRknFyc3R1dXZ3eHl6ent8fX5/gICio6SlpqeGh4iJiYmIh4aFhISDgoGAf35+np2cm5uaeHd2dXRzc3JxcG9ubm1sa2ppaImIh4aFhWNiYWBfXl5dXFtaWVhYV1ZVVFV3eHl6entbXF1dXl9gYWJjY2RlZmdoaGlqjI2Oj5CQcHFyc3N0dXZ3eHl5ent8fX5+f6Gio6SlpoWGh4iJiYmIh4aFhYSDgoGAgH+fnp2dnJt5eHd2dXV0c3JxcG9vbm1sa2pqiomIh4eGZGNiYWBfX15dXFtaWllYV1ZVVHZ3eHl5elpbXFxdXl9gYWFiY2RlZmdnaGmLjI2Oj49vcHFyc3N0dXZ3eHl6e3x8fX5/n6ChoqOjhYaHiImKi4uKiYiHh4aFhISDgp6dnJuamnx8e3p5eHh3dnV0dHNycXBwb26Ih4aFhINoaGdmZWRkY2JhYWBfXl1dXFtacXFyc3N0dV9gYGFiY2RlZmdoaWlqa2xtboSFhoeHiIl1dnd4eXp6e3x9fn+AgYKDg4SYmZqam5ydi4yNjo+QkZGQkI+OjYyMi4qJmZiXlpWUk4OCgYGAf359fXx7enl5eHd2dYKBgYB/fn1vbm1tbGtqaWloZ2ZmZWRjYmJha2prbG1uZGVmZ2hoaWprbG1ub3BwcXJzdH5+f4CBgnp7fH1+f4CBgYKDhIWGh4iJioqRkpOUlZWRkpOTlJWWl5iXlpWVlJOSkZGQk5KRkI+OioqJiIeGhoWEg4KCgYB/fn59fHx7enp5eHZ2dXRzcnJxcG9ubW1sa2ppaGdnZmVmZmdoaWpra2xtbm9wcXFyc3R1dnZ3eHl6e3x8fX5/gIGBgoOEhYaHh4iJiouMjI2Oj5CRkpKTlJWWl5eYmZqamZiXlpWUlJOSkZCPj46NjIuKiYmIh4aFhISDgoGAf35+fXx7enl5eHd2dXR0c3JxcG9ubm1sa2ppaWhnZmVlZmdoaWpqa2xtbm9vcHFyc3R1dXZ3eHl6ent8fX5/gICBgoOEhYWGh4iJiouLjI2Oj5CQkZKTlJWWlpeYmZqamZiXlpaVlJOSkZCQj46NjIuLiomIh4aFhYSDgoGAgH9+fXx7enp5eHd2dXV0c3JxcHBvbm1sa2pqaWhnZmVlZmdoaGlqa2xtbm5vcHFyc3N0dXZ3eHl5ent8fX5+f4CBgoOEhIWGh4iJiYqLjI2Oj4+QkZKTlJSVlpeYmZqamZiXl5aVlJOSkpGQj46NjIyLiomIh4eGhYSDgoGBgH9+fXx8e3p5eHd3dnV0c3JxcXBvbm1sbGtqaWhnZmZlZmdnaGlqa2xsbW5vcHFycnN0YXqGfXWOe2Zxa21lhpZ3mpGRd3Jlg5ypsa7BjXFuWXNqWm9Wd3aEZIN3dZi+uKe3fXZZXm5odV9qeXhmenp6erqjlJuofmBadFh9hVVgbVdRV3NrXauJjI2baGU9aVtHNlVZQVVFOEBLR3ZtaoJtQlJAL009Q09MTEBBUlhQVoSdppmlV1d4V4B2gX9pXX50W3ViaLaUvbu1eoN5XnZ6ZXl0ZmFrfWB8ZZ+vvrWneHt2cGh7YYBpfWhmhWd8a6ChvJymdoRwY3t/eXV5aGVzYlt4dIuFiaJ8TklbTEw/VjpPWkZDVFlCT2Nsf355hDhAR1RcTkhkaU9Wb3FZY6CPj52OiXd7Ym90gGtveGR7ZGdhcJWmmJ+rl3Z9gIFxdXh5cH1ugmtqeKeuuJ2YrXh+eoZ7jGx7hnd3iH92hHSqpKShl25oeYF8bm9nZGdwW11ZZmyNl32Bd2VmZVJLSFpYTU9JVFBASEV7aGpxakxMVFJZZGJSY1lfZ2djYmuMhZuLoG5lfGhuanZnZm9lcXpwcXqkio2QlHd2cHBthm+EfIp7f3qCd4KltKSjn4yBh3qCf455jH2ChXuKfoiqoZydqHKCcXZ4a252e3JpaXNnam6IgHx5iWdbV09XVFtcWFZYUF1RS15oant2c1ROVltVWmFnZmJfYGxocV+IjImVknB2a3ppZ3psdnR1eHh7c26LkJKclZR4eG95fH51fXeHhISKh4ihs6Orn7KQg4mMhIaOe4iFf4CKgoSelqCio5J0cndrbXdwZ3NwcWhlZGF9fn97g3xWU2RiYFhiV1pgUVdYUE5QbXWAfXZSWmRkZ1pmYmlbZl1lZm5siIWUkZNqcnVocnBxcW1ocXZxcGtskJqVnZt6f3h3goJ8hIeEhYSChI6LpLGwrqSQhomIh36Li4mIgoWCd35+mqGTm5x3d3pwbnJua3BuY2tpYGldfoF9g3ljYFxaW19TW1xYWFJbUE9bcXZxenZhYlhfWmFeYGBgZGRoZ2Fki4uNiY5xbGplc21taGh2b292eHhwmZOXm5lzgHZ8e3h9e4aAhImDiIeDq7KosKeJjoWHg4OBgYKFgnp+g3Z/mp6fmZaSdndza3NtZ21nZWZjaGVghn+Fg4N+X1laXVlXYWFgWVtWXlxZdXp4fnd7XWBaYV1fYGFfYmdfX2Joh4aIhYaGZnBrZnFnam5panFrb3NyeZWTm5afeHp4f4KAhoCGgIuJjImMi6ysqK+qioKFgoOIhIGChH2AeYB8fp6dlZaScXJscHBubWhvZWtoZGJoY4SAh4CEYl9eXlxgYGFfYFpeWVxVW3p2d3h5WFlaW1xdXV5fYGFiYmNkZYeIiYqKamtsbW1ub3BxcnNzdHV2d5mam5ucfH1+fn+AgYKDg4SFhoeIiauqqaiohoWEg4KBgYB/fn18e3t6eZmYmJeWdHNycXBwb25tbGtramloZ4iHhoWEYmFgYF9eXVxbWlpZWFdWVXZ2d3h4WFlaW1tcXV5fYGFhYmNkZYeIiYmKi2tsbG1ub3BxcXJzdHV2d5mZmpucnXx9fn+AgYKCg4SFhoeHiKqqqqmop4WEg4KCgYB/fn19fHt6eXiZmJeWlXNycnFwb25tbGxramloZ2eHhoWEhGFhYF9eXVxcW1pZWFdWVlV2d3d4eVlaWltcXV5fX2BhYmNkZWWHiImKi2prbG1ub3BwcXJzdHV1dneZmpucnXx9fn+AgIGCg4SFhoaHiImrqqmop4WEhIOCgYB/fn59fHt6eXmZmJeWlXNzcnFwb25ubWxramloaGeHhoWFhGJhYF9eXV1cW1pZWFhXVlV1dnd4eVhZWltcXV5eX2BhYmNjZGWHiImKi2prbG1ubm9wcXJzdHR1dneZmpucnHx9fn9/gIGCg4SEhYaHiImrqqmop6eFhIOCgYCAf359fHt6enmZmJeXlpVzcnFwb29ubWxramppaGeHh4aFhINhYF9fXl1cW1pZWVhXVlV2dnd4eXlZWltcXF1eX2BhYmJjZGVmiImKiotrbG1tbm9wcXJyc3R1dnd4mpqbnJ19fX5/gIGCg4OEhYaHiIiJqqmpqKeFhIOCgYGAf359fHx7enl4mJiXlpVzcnFxcG9ubWxra2ppaGdmh4aFhINhYGBfXl1cW1taWVhXVlVVdnd4eHlZWltbXF1eX2BgYWJjZGVmiIiJiotra2xtbm9wcXFyc3R1dnZ3mZqbnJ18fX5/gIGBgoOEhYaHh4iJqqqpqKeFhIODgoGAf359fXx7enl4mZiXlpVzcnJxcG9ubW1sa2ppaGdnh4aFhISDYWBfXl1cXFtaWVhXV1ZVdnZ3eHl6WVpbXF1eX19gYWJjZGRlh4iJiouMa2xtbm9vcHFyc3R1dXZ3mZqbnJ2dfX5/gICBgoOEhYWGh4iJiqqpqKemhISDgoGAf39+fXx7enl5eJiXlpaVc3JxcG9ubm1sa2ppaWhnZoaGhYSDYWBfXl5dXFtaWVhYV1ZVVHZ3eHl6WVpbXF1dXl9gYWJjY2RlZoiJiouLa2xtbm5vcHFyc3N0dXZ3eJqbm5ydfX5+f4CBgoOEhIWGh4iJiaqpqKinhYSDgoGAgH9+fXx7e3p5eJiYl5aVc3JxcHBvbm1sa2pqaWhnZoeGhYSDYWBfX15dXFtaWllYV1ZVVHZ3eHl5WVpbXFxdXl9gYWJjZGRlZoeIiYqKi2xtbm9wcXJzdHV1dnd4eZiZmZqbnH+AgYKDhIWGhoeIiYqLjKinpqWko4eGhYWEg4KBgYB/fn19fJWUk5KRkHZ2dXRzcnJxcG9ubm1sa2qBgH9+fmZlZGNiYmFgX15eXVxbW1pxcXJzdGBhYmJjZGVmZ2hpamtrbG2BgoOEhXNzdHV2d3h5ent8fH1+f4CSk5SUlYWGh4iJiouMjY2Oj5CRkpKhoJ+enY6NjIuKiomIh4aGhYSDgoKOjYyLin18e3t6eXh3d3Z1dHNzcnF7enl4d2xra2ppaGdnZmVkY2NiYWFqa2xsbWZnaGlpamtsbW5vcHFycnN7fHx9fnl6e3t8fX5/gIGCg4OEhYaMjI2Oj4yMjY6PkJGSk5SUlZaXmJmbmpmYl5STk5KRkI+Pjo2Mi4uKiYiIh4aFhIODgoGAf359fXx7enl4eHd2dXRzcnJxcG9ubW1sa2ppaGdnZmVmZmdoaWpra2xtbm9wcXFyc3R1dnZ3eHl6e3x8fX5/gIGBgoOEhYaHh4iJiouMjI2Oj5CRkpKTlJWWl5eYmZqamZiXlpWVlJOSkZCPj46NjIuKiomIh4aFhISDgoGAf39+fXx7enl5eHd2dXR0c3JxcG9ubm1sa2ppaWhnZmVlZmdoaWpqa2xtbm9vcHFyc3R1dXZ3eHl6ent8fX5/gICBgoOEhYWGh4iJiouLjI2Oj5CQkZKTlJWWlpeYmZqamZiXlpaVlJOSkZGQj46NjIuLiomIh4aGhYSDgoGAgH9+fXx7e3p5eHd2dXV0c3JxcHBvbm1sa2pqaWhnZmVlZmdoaGlqa2xtbm5vcHFyc3N0dXZ3eHl5ent8fX5+f4CBgoOEhIWGh4iJiYqLjI2Oj4+QkZKTlJSVlpeYmZmamZiYl5aVlJOSkpGQj46NjYyLiomIh4eGhYSDgoKBgH9+fXx8e3p5eHd3dnV0c3JxcXBvbm1sbGtqaWhnZ2hoYmJhYWFhYWFgYGBggIKEhV9fX19eXl5eXl5dXZ6foKFgYWFiY2RlZmdoaWmrrK2ubm9wcXFyc3R1dnd4uLm6uXl4d3Z2dXRzcnJxr66trG1sa2pqaWhnZmZlZKCfn55gX15eXVxbWlpZWFeSkZCPU1JSUVBPTk5NTEtKhIOCgklKS0xNTk9QUFFSU42Oj49YWFlaW1xdXl9gYJmam5tlZmdoaGlqa2xtbm+mp6eoc3R1dnd4eHl6e3x9s7O0tH9+fXx7e3p5eHd3dqiop6ZycXBvbm5tbGtqapuamZhmZWRjYmJhYF9eXl2NjIuKWVhXVlZVVFNSUlFQf359fU9PUFFSU1RVVldXWIeIiYpdXl9fYGFiY2RlZmeUlZaWa2xtbm9vcHFyc3SgoaKjeHl6e3x9fn9/gIGCra6vr4SDg4KBgH9/fn18e6OioaF3d3Z1dHNzcnFwb2+VlJOSa2ppaGdnZmVkY2Nih4aFXl5dXFtaWllYV1ZWeXl4d1RVVVZXWFlaW1xdXYKCg4RiY2RlZWZnaGlqa2yOj5CRcHFyc3R1dXZ3eHl6nJydnn5/gICBgoOEhYWGqKmqq4mIh4aFhISDgoGAf6Cfnp17enl5eHd2dXR0c3KSkZGQbm1sa2ppaWhnZmVkhYSDgmBfXl5dXFtaWVhYV3d2dXZWV1hYWVpbXF1dXoCBgoNjY2RlZmdoaGlqa2yOj5CQcHFyc3N0dXZ3eHl5m5ydnn5+f4CBgoOEhIWGh6mqq6qIh4aGhYSDgoGAgH+fnp17e3p5eHd2dXV0c3KSkpGQbm1sa2pqaWhnZmVlhYSDgmBfX15dXFtaWllYV3d3dnZWVldYWVpbXFxdXl+BgoOEY2RlZmdnaGlqa2yOj4+QcHFycnN0dXZ3d3h5m5ydnn1+f4CBgoKDhIWGh6mqqqqIh4eGhYSDgoKBgH+fn56de3p5eHd3dnV0c3JxkpGQj21sbGtqaWhnZmZlhYSDg2FgX15dXFtbWllYV3h3dnZVVldYWVpaW1xdXl+BgoKDY2RlZWZnaGlqa2tsjo+QkXBxcnN0dXZ2d3h5epydnX1+f4CBgYKDhIWGhqipqquJiIeGhYSDg4KBgH+gn56de3p5eHh3dnV0c3NykpGQkG1tbGtqaWhoZ2ZlZIWEg4JgX15dXVxbWllYV3h3dnZVVldYWVlaW1xdXl6BgYKDY2RkZWZnaGlpamtsjo+QkXBxcnN0dHV2d3h5epycnZ5+f3+AgYKDhISFhoepqquqiIeGhYWEg4KBgH+gn56de3p6eXh3dnV0dHNykpGRkG5tbGtqaWloZ2ZlZIWEg4JgX15eXVxbWllZWFd3dnZ2VldXWFlaW1xdXV5fgYKDYmNkZWZnaGhpamtsjo+PkHBxcnNzdHV2d3h4eZucnZ5+fn+AgYKDg4SFhoepqquqiIeGhoWEg4KBgYB/n56enXt6eXh3dnZ1dHNyk5KRkG5tbGtramloZ2ZlZYWEg4JgYF9eXVxbWlpZWFd3d3Z2VlZXWFlaW1tcXV5fgYKDg2NkZWZmZ2hpamtsbI6PkJFxcXJzdHV2d3d4eZucnZ59fn+AgYGCg4SFhoepqaqqiIiHhoWEg4KCgYB/n5+enXt6eXh3d3Z1dHNycpKRkI9tbGxramloZ2dmZYWEhINhYF9eXVxcW1pZWFd4d3Z2VVZXWFlaWltcXV5fgYKCg2NkZWVmZ2hpamprbI6PkJFwcXJzdHV1dnd4eXqcnZ2efn+AgIGCg4SFhYaoqaqriYiHhoWEhIOCgYB/oJ+enXt6eXl4d3Z1dHNzcpKRkJBubWxramloaGdmZWSFhIOCYF9eXV1cW1pZWFhXd3Z1dlZXWFhZWltcXV5egIGCg2NjZGVmZ2hpaWprbI6PkJBwcXJzdHR1dnd4eXmbnJ2efn5/gIGCg4SEhYaHqaqrqoiHhoWFhIOCgYCAoJ+enXt6enl4d3Z1dXRzcpKSkZBubWxramppaGdmZWSFhIOCYF9fXl1cW1pZWVhXd3Z2dlZXV1hZWltcXF1eX4GCg4RjZGVmZ2doaWprbI6Pj5BwcXJyc3R1dnd4eHmbnJ2efX5/gIGCgoOEhYaHqaqqqoiHh4aFhIOCgYGAf5+enp17enl4d3Z2dXRzcnGSkZBubWxra2ppaGdmZmWFhIODYGBfXl1cW1taWVhXeHd2dlVWV1hZWltbXF1eX4GCg4NjZGVmZmdoaWpra2yOj5CRcXFyc3R1dnZ3eHmbnJ2efX5/gIGBgoOEhYaGqamqq4iIh4aFhIODgoGAf6Cfnp17enl4eHd2dXRzcnKSkZCPbW1sa2ppaGdnZmVkhISDgmBfXl1cXFtaWVhXeHd2dlVWV1hZWVpbXF1eX4GBgoNjZGRlZmdoaWpqa2yOj5CRcHFyc3R1dXZ3eHl6nJydnn5/f4CBgoOEhYWGh6mqq4mIh4aFhISDgoGAf6Cfnp17enl5eHd2dXR0c3KSkZGQbm1sa2ppaWhnZmVkhYSDgmBfXl5dXFtaWVhYV3d2dXZWV1hYWVpbXF1dXoCBgoNjY2RlZmdoaGlqa2yOj5CQcHFyc3N0dXZ3eHh5m5ydnn5+f4CBgoODhIWGh6mqq6qIh4aGhYSDgoGAgH+fnp2de3p5eHd2dXV0c3KSkpGQbm1sa2pqaWhnZmVlhYSDgmBfX15dXFtbWllYV3d2dXVWV1hZWltcXV1eX2CAgIGCZWVmZ2hpamtsbW5ujI2OcnN0dXZ3d3h5ent8mJmam4CBgoOEhYaHiIiJiqWmp6eMi4uKiYiHh4aFhIObmpmYf39+fXx7e3p5eHd3jYyLinNycXBwb25tbGxrf359fGdmZWRkY2JhYGBfXnFwb29cXV5fYGFiY2RkZWZ5ent7a2xtbW5vcHFyc3R1hoeHiHl6e3x9fn5/gIGCg5OTlJWHiImKi4yNjo+PkJ6foKCTkpGQkI+OjYyMi4qVlJOShoWEhIOCgYCAf359hoaFhHl4eHd2dXV0c3JxcXh3dnVtbGtqaWloZ2ZlZWRqaWhjY2RlZmdoaWpra2xzc3R1cXJzdHR1dnd4eXp7f4CBgn+AgYKDhIWFhoeIiYyNjo6Ojo+QkZKTlJWWlpeZmZqZmZiXlpWUk5OSkZCPjo6NjIuKiYiIh4aFhIODgoGAf359fXx7enl4eHd2dXRzcnJxcG9ubW1sa2ppaGdnZmVmZmdoaWpra2xtbm9wcXFyc3R1dnZ3eHl6e3t8fX5/gIGBgoOEhYaGh4iJiouMjI2Oj5CRkZKTlJWWl5eYmZqamZiXlpWVlJOSkZCPj46NjIuKiomIh4aFhISDgoGAf39+fXx7enl5eHd2dXR0c3JxcG9ubm1sa2ppaWhnZmVlZmdoaWpqa2xtbm9vcHFyc3R0dXZ3eHl6ent8fX5/f4CBgoOEhYWGh4iJioqLjI2Oj5CQkZKTlJWVlpeYmZqamZiXlpaVlJOSkZGQj46NjIuLiomIh4aGhYSDgoGAgH9+fXx7e3p5eHd2dXV0c3JxcHBvbm1sa2pqaWhnZmVlZmdoaGlqa2xtbm5vcHFyc3N0dXZ3eHh5ent8fX5+f4CBgoODhIWGh4iJiYqLjI2Ojo+QkZKTlJSVlpeYmZmamZiYl5aVlJOSkpGQj46NjYyLiomIh4eGhYSDgoKBgH9+fXx8e3p/hIqPlZqSlZeZmpucnJybmpmXlJGOt7Sysa93c29qZWBbV1NPS0dDPzs4dnNwbWsnJiUkIyMkJCUnKSsuMTQ4e3+EiI1TWF1jaG1zeH6DiI2Slpuf4eTn6eqtra2trKupqKWjoJ2al5OPx8O+ubR0b2plYFxXUk5JRUE9OjYzamhlY2EmJSQjIyMjJCUmJykrLS8xbG5xdXlGSk9TWFxgZWlscHR3en2Auby9v8GLjI2Ojo6OjY2MiomIhoSCtbOxrqx1c3BubGpnZWNiYF5dXFtajIyMiolVVFNSUlJSUlNTVFVWV1lajY+Rk5SWaGpsbnBydHV3eXp8fX5/sLCxsbGxgoKBgH9+fXt6eHZ0cm9tmJWSj46MXlxbWVdWVFNRT05NS0pJdHNycXFwRERERUVFRkdISUpMTU9RU3+BhIaIYmRnam1wc3Z5fH+ChYiLjrm8vr/AmZqam5ubm5ybm5uampmYl7y7ubi2jo2LiYaEgoB9e3h1c3Bua42Kh4SCW1hWU1FOTEpIRkRCQD49O1xbWltbOjs8PT4/QUJERkdJS01PUXV3eXx+X2JkZ2lsbnBzdXh6fH+Bg6epq62uj5GSlJWXmJmbnJ2enp+goMLCw8HAnZuZmJaUkpCOjIqIhYOBf56cmZeVcm9ta2lnZWNhX11cWlhWVXVzcnFvTUxLSklIR0dGRkVFRERERGVlZWZoakpMTlBSVFZYWltdX2FjZYmLjY6QknN1dnh6e31/gIKDhIaHiKusra6vsI+QkZKSk5SUlZWVlpaWlri4uLe1tJGPjYuKiIaEg4F/fXt6eHaWlJKRj2xqaWdmZGNhYF5dXFtZWFd3dnV0c1FQT05OTUxMS0pKSUlJSEhpaGlrbExOT1FSVFVXWVpcXV9hYmSHiIqLjW1vcHJzdXZ4eXp8fX+AgYKlpqeoqomKjI2Ojo+QkZKTlJSVlpa4ubm4tpSTkpCPjo2LiomHhoWDgoCgn52cm3h3dXRycW9ubWtqaGdmZGODgYB/fVtaWFdWVVRSUVBPTk1MS0pqaWlpakpLS0xNTk9QUVJTVFVWV1h6e3x+f19gYWJjZWZnaGlrbG1ucHGTlZaXmZp6e3x+f4CCg4SFh4iJioyur7Cwr66NjIyLi4qJiYiIh4aGhYSlpKOjoqF/fn59fHt6eXl4d3Z1dHOTk5KRkI9sa2ppaGdmZWRjYmFgX15cfXx8fX1dXV5eX19gYGFiYmNjZGRlh4eIiIloaWlqamtsbG1tbm9vcHBxk5OUlZV1dnZ3eHh5enp7fHx9fn9/oaKhoKB9fXx7enl4d3d2dXRzcnJxkZmYl5d0dHNycXBvb25tbGtqaWloiIeGhoVjYmFgX19eXVxbWllZWFdWdnZ2d3hXWFlaW1xcXV5fYGFiYmNkhoeIiYppamtsbW1ub3BxcnJzdHV2mJmampt7fH19fn+AgYKDg4SFhoeIqquqqamGhoWEg4KBgYB/fn18e3t6mpmYmJd1dHNycXBwb25tbGtramloiIiHhoWEYmFgYF9eXVxbW1pZWFdWd3Z2d3h4WFlaW1tcXV5fYGBhYmNkhoeIiImKamtrbG1ub3BxcXJzdHV2dpmZmpucfHx9fn+AgYGCg4SFhoeHiKqqqqmohoWEg4KCgYB/fn19fHt6eZqZmJeWdHNycnFwb25tbGxramloZ4iHhoWEYmJhYF9eXVxcW1pZWFdXVnZ2dnd4WFlZWltcXV5fX2BhYmNkZIeHiImKamprbG1ub29wcXJzdHV1dpiZmpuce3x9fn+AgIGCg4SFhYaHiKqrqqmohoWEhIOCgYB/fn59fHt6eZqZmJeWdHNzcnFwb25ubWxramloaIiHhoWFY2JhYF9eXl1cW1pZWFhXVnZ1dnd4WFhZWltcXV1eX2BhYmNjZIaHiImKi2prbG1ubm9wcXJzc3R1dpiZmpubnHx9fn5/gIGCg4SEhYaHiKqrqqmoqIWFhIOCgYCAf359fHt6epqZmJeXlnRzcnFwb29ubWxramppaGeHh4aFhGJhYF9fXl1cW1paWVhXVlV2dnd4eVhZWltcXF1eX2BhYWJjZGWHiImJimprbGxtbm9wcXJyc3R1dneZmpqbnHx9fX5/gIGCgoOEhYaHiIiqqqmpqIaFhIOCgYGAf359fHx7enmZmZiXlnRzcnFxcG9ubWxra2ppaGeIh4aFhGJhYWBfXl1cW1taWVhXVlZ2dnd3eFhZWlpbXF1eX2BgYWJjZGWHiIiJimpra2xtbm9wcHFyc3R1dnaYmZqbnHt8fX5/gIGBgoOEhYaGh4iqq6qpqKeFhIODgoGAf359fXx7enmamZiXlpVzcnJxcG9ubW1sa2ppaGiIh4aFhIRiYWBfXl1dXFtaWVhXV1Z2dnZ3eHlZWVpbXF1eXl9gYWJjZGRlh4iJiotqa2xtbm9vcHFyc3R0dXZ3mZqbnJx8fX5/f4CBgoOEhYWGh4iJq6qpqKeFhISDgoGAf39+fXx7enl5mZiXlpZ0c3JxcG9vbm1sa2ppaWhnh4aGhYRiYWBfXl5dXFtaWVlYV1ZVdnZ3eHlYWVpbXF1dXl9gYWJiY2Rlh4iJiopqa2xtbW5vcHFyc3N0dXZ3mZqbm5x8fX5+f4CBgoODhIWGh4iJq6qpqKiGhYSDgoGAgH9+fXx7e3p5mZiYl5Z0c3JxcHBvbm1sbGtqaWhoh4aFhIOCYmFgYF9eXVxcW1pZWVhXdHR1dnd3W1xdXl5fYGFiY2RlZmdnhIWGh4eIbm9vcHFyc3R1dnd4eHl6lZaWl5iZgYGCg4SFhoeIiYmKi4yNjqalpKOiiomIiIeGhYSEg4KBgYB/fpOSkZCPeXl4d3Z1dXRzcnFxcG9ubYB/fn18aWhnZmVlZGNiYWFgX15eXW5ub3BxYWJjZGVlZmdoaWprbG1ubn5/gIGCdHV2d3d4eXp7fH1+f3+AgY+QkZGSh4iIiYqLjI2Oj5CQkZKTlJ+fnp2ckZCPjo2NjIuKiYmIh4aGhY2Mi4qJgH9+fn18e3p6eXh3dnZ1dHp5eHd2b25ubWxramppaGdnZmVkY2doaWlqZ2hpamtsbW1ub3BxcnN0dXh5eXp7ent8fX5+f4CBgoOEhYaGh4iJiouMjY2Oj5CRkpOTlJWWl5iYmZqZmZiXlpWUk5OSkZCPjo6NjIuKiYiIh4aFhIODgoGAf359fXx7enl4eHd2dXRzc3JxcG9ubW1sa2ppaGhnZmVlZmdoaWpra2xtbm9wcHFyc3R1dnZ3eHl6e3t8fX5/gIGBgoOEhYaGh4iJiouMjI2Oj5CRkZKTlJWWl5eYmZqamZiXlpWVlJOSkZCPj46NjIuKiomIh4aFhISDgoGAf39+fXx7enp5eHd2dXR0c3JxcG9vbm1sa2ppaWhnZmVlZmdoaWlqa2xtbm9vcHFyc3R0dXZ3eHl6ent8fX5/f4CBgoOEhYWGh4iJioqLjI2Oj5CQkZKTlJWVlpeYmZqamZiXlpaVlJOSkZGQj46NjIuLiomIh4aGhYSDgoGAgH9+fXx7e3p5eHd2dnV0c3JxcHBvbm1sa2tqaWhnZmVlZmdoaGlqa2xtbW5vcHFyc3N0dXZ3eHh5ent8fX5+f4CBgoODhIWGh4iJiYqLjI2Ojo+QkZKTlJSVlpeYmZmamZiYl5aVlJOSkpGQj46NjYyMjIyMjY1/fXt5d3V0cnBubGppZ2VjYV9dkJCQkJGRUE9OTUxLS0pJSEdHRkVERUZHSImKi4yNjU5PUFFRUlNUVVZXWFlZWltcXV6enp+goaJkZWZnaGlpamtsbW5vcHFxcnN0srKztLW2ent8fHt6eXh4d3Z1dHRzcnFwcKmop6ampWppaGhnZmVkZGNiYWBgX15dXFuTkpGQj45WVVRTU1JRUE9PTk1MS0tKSktMg4SFhYaHUlNUVVZXWFhZWltcXV5fYGBhYpeYmZmam2hpamtsbW5vcHBxcnN0dXZ3eHirrK2urq9/gICBgYCAf359fHx7enl4eHd2paSjoqGgcHBvbm1sbGtqaWhoZ2ZlZGRjYo+OjYyLilxcW1pZWFhXVlVUVFNSUVBQT1B9fX5/gIFXV1hZWltcXV5fX2BhYmNkZWZnkZGSk5SVlW5vb3BxcnN0dXZ3d3h5ent8faWlpqeoqamEhYaHh4aFhYSDgoGBgH9+fXyhoJ+enZybdnV0dHNycXBwb25tbGxramloiomJiIeGhWJhYGBfXl1cXFtaWVhXV1ZVVHZ3eHl6e3tbXF1eXl9gYWJjZGRlZmdoaWlqjI2Oj5CRcHFyc3R0dXZ3eHl6ent8fX5/f6Kio6SlpoWGh4iJiomIh4aFhISDgoGAf3+fnp2cnJt5eHd2dXR0c3JxcG9vbm1sa2ppiomIh4aGZGNiYWBfXl5dXFtaWVlYV1ZVVHZ3eHl6elpbXF1dXl9gYWJiY2RlZmdoaGmLjI2Oj5BvcHFyc3N0dXZ3eHh5ent8fX5+oKGio6SlhIWGh4iJiYmIh4aGhYSDgoGBgKCfnp2dnHp5eHd2dnV0c3JxcHBvbm1sa2uLiomIiIdlZGNiYWBgX15dXFtaWllYV1ZVdnZ3eHh5WVpbW1xdXl9gYWFiY2RlZmZnaIqLjI2Ojm5vcHFxcnN0dXZ3d3h5ent8fH2foKGio6SDhIWGh4eIiYmIh4eGhYSDgoKBoaCfn56de3p5eHd3dnV0c3JycXBvbm1sbIyLiomJiIdlZGNiYWFgX15dXFxbWllYV1Z3dnZ3d3h5WVpaW1xdXl9fYGFiY2RlZWZniYqLjI2Njm5vcHBxcnN0dXV2d3h5ent7fJ6foKGio6ODhIWGhoeIiYmJiIeGhYSEg4KioaCgn56de3p5eXh3dnV0c3NycXBvbm5tbIyLi4qJiGZlZGNjYmFgX15dXVxbWllYWFd3dnV2d3hYWFlaW1xdXl5fYGFiY2NkZWZniYqLi4yNbW5ub3BxcnN0dHV2d3h5eXp7fJ6foKGhooKDhISFhoeIiYqJiIeGhYWEg4KioqGgn558e3p6eXh3dnV1dHNycXBvb25tjYyMi4qJZ2ZlZGRjYmFgX19eXVxbWllZWHh3dnZ2d1dXWFlaW1xcXV5fYGFiYmNkZWaIiYqKi4xsbW1ub3BxcnJzdHV2d3h4eXp7nZ6foKChgYKDg4SFhoeIiImJiIeHhoWEg6OjoqGgn318fHt6eXh3dnZ1dHNycXFwb26Ojo2Mi4poZ2ZmZWRjYmFgYF9eXVxbW1pZeXh4d3Z2VVZXWFlaW1tcXV5fYGBhYmNkZYeIiImKi2trbG1ub3BxcXJzdHV2dnd4eXqcnZ6en6ChgYGCg4SFhoeHiImJiIiHhoWEpaSjoqGgn319fHt6eXh4d3Z1dHNycnFwb4+Pjo2Mi4poZ2dmZWRjYmJhYF9eXVxcW1p6eXl4d3Z2VVZXWFlZWltcXV5fX2BhYmNkZIeHiImKi2prbG1ub29wcXJzdHV1dnd4eXqcnZ2en6CAgIGCg4SFhYaHiImKiYiHhoWEpaSjoqGhf359fHt6eXl4d3Z1dHRzcnFwb5CPjo2Mi2lpaGdmZWRjY2JhYF9eXl1cW1p7enl4d3ZUVVZXWFhZWltcXV1eX2BhYmNjhYaHiImKaWprbG1ubm9wcXJzc3R1dnd4eZubnJ2en35/gIGCg4SEhYaHiImJiYiHhoampaSjoqKAf359fHt7enl4d3Z1dXRzcnFwkZCPjo2NamppaGdmZWVkY2JhYF9fXl1cW3x7enl4d1VUVVZWV1hZWltcXF1eX2BhYWKEhYaHiIloaWprbGxtbm9wcXJyc3R1dnd3mpqbnJ2efX5/gIGCgoOEhYaHiIiJiYiHh6empaSko4GAf359fHx7enl4d3d2dXRzcnGSkZCPjo6Na2ppaGdmZmVkY2JhYWBfXl1cfXx7enl4eFZVVVVWV1hZWlpbXF1eX2BgYYOEhYaHiIhoaWpra2xtbm9wcHFyc3R1dnaYmZqbnJ2efX5/gIGBgoOEhYaGh4iJiYmIqKempaWko4GAf35+fXx7enl4eHd2dXRzc3KSkZCQj45sa2ppaGhnZmVkY2JiYWBfXl1dfXx7enp5V1ZVVFVWV1hZWVpbXF1eXl9gYYOEhYaGh2doaWlqa2xtbm9vcHFyc3R0dXaYmZqbnJx8fX5/f4CBgoOEhYWGh4iJiomIqKenpqWkgoGAf39+fXx7enp5eHd2dXR0c5OSkZGQj21sa2ppaWhnZmVkZGNiYWBfXl5+fXx7e3pYV1ZVVFVWV1dYWVpbXF1dXl9ggoOEhYWGZmdoaGlqa2xtbW5vcHFyc3N0dZeYmZqbm3t8fX5+f4CBgoODhIWGh4iJiYmpqKinpqWDgoGBgH9+fX18e3p5eXh3dnV1k5KSkZCPb25ubWxramppaGdmZmVkY2JiYX18e3p5eFtaWllYV1dYWVpbXF1eX2BgYWJ9fn+AgYFoaWprbG1ub3BxcXJzdHV2d3h5kZKTlJWVloCBgoKDhIWGh4iJiouLjI2Oj6Sko6KhoJ+KiYiHhoaFhIOCgoGAf35+fXyOjYyLioqJdnV0c3NycXBvb25tbGtramloeHd2dXRzcmJhYF9fXl5eX2BhYmNkZWZnZ3Z3eHh5entvcHBxcnN0dXZ3eHh5ent8fX5/i4yMjY6PhYaHiImKiouMjY6PkJGSkpOUlZ6dnZybmpGQj4+OjYyLi4qJiIeHhoWEg4OIh4aFhIN9fHx7enl4eHd2dXR0c3JxcHBvcnFwb25taWhoZ2ZlZGRlZmZnaGlqa2xtbm9wcXJzc3R1dnd3eHl6e3x9fX5/gIGCgoOEhYaHiIiJiouMjY2Oj5CRkpKTlJWWl5iYmZqZmZiXlpWUlJOSkZCPjo6NjIuKiYmIh4aFhIODgoGAf35+fXx7enl4eHd2dXRzc3JxcG9ubW1sa2ppaGhnZmVlZmdoaWpra2xtbm9wcHFyc3R1dnZ3eHl6e3t8fX5/gIGBgoOEhYaGh4iJiouMjI2Oj5CRkZKTlJWWlpeYmZqamZiXlpWVlJOSkZCQj46NjIuKiomIh4aFhYSDgoGAf39+fXx7enp5eHd2dXR0c3JxcG9vbm1sa2ppaWhnZmVlZmdoaWlqa2xtbm9vcHFyc3R0dXZ3eHl6ent8fX5/f4CBgoOEhYWGh4iJioqLjI2Oj4+QkZKTlJWVlpeYmZqamZiXl5aVlJOSkZGQj46NjIyLiomIh4aGhYSDgoGBgH9+fXx7e3p5eHd2dnV0c3JxcHBvbm1sa2tqaWhnZmVlZmdoaGlqa2xtbW5vcHFyc3N0dXZ3eHh5ent8fX5+f4CBgoODhIWGh4iJiYqLjI2Ojo+QkZKTk5SVgpunnpavp5KNhoZ7nKmJqp+egnxtiXR9gnqKiWtmUGiejqKHpaOvjmlbWDdcVUVVXFQ4PU1HVD5JV1dFWVlZWJmCc3qHnoJ9Wj9mcEJOXUhES2pjV2lITVBfbGtEcmaQgqGnkKeYjVpnZFlRT2dSY3NhUG9eZHBtbWFjc3lxd6W+x7rHsK/OcpmOlpJ7boyBZn9qboNehoN7dn5yVWyljqGaioOMnEZhSEpYZl5QV1pVT0daP19IXEdFZEZbSn+Am3uFi5qISGJnY2FnV1ZmVlFvblNPVG9LUU5iVVZ+lnySn42LnnJebFBbb25pdFlhaHV9b2mFinB3kJJ6hMGwsL6vqsXHfYiMloCCiXSJb3Fpd218bHF8Z3F3d3dllJWVipWEl35PW11jbFFMYVddWWVaa0taZVZWZ15VY32Jg4OAd3h0XWdkWFpUU1diT1NQX2dhbVVbUmptbVxXfJGQhoqFko9bZWN1Y2VsZm5tdXN6hYNzhHqAiIiEg7GtpryswbGml4KGgYt6d39zfoV5eX+Famttb3NwaGZimoKVjJeHioJoW2RkcWJhXWtgZllhXmxXa1xhZFppXYiJgHp8h3SGVlxfVFljamJbXGheY2ljXFpZa2thX1ljgouNi4uOiJdsZ3xmant2c3Vwd3x2e4KIh4OAgo2JkoCpraq2s7G1qZWBfo+AiISDhYSEe3RucXJ6cW9ycGZukZGGjYWTjo1wa2pgcWFpXHBvYmhrY2RtWmdjXl9pYWJ9dX+BgnN4d1xSVmJcVWNhZFxbXFtXWl1aZF9bW21sjoeTio+WiZFybGtvbHWAfXZ0e4WFiXuHhIp8iH6Gh4+uqaa1srOqr4+BiYWFhH53foF7eXJwcnp0enZ1eHBsl5WOlJWRkI1paHFsY29ubGFvZWhmZl1qamhnYWRhVl1+eIByenx5fF9WVlxaWF9fVV9fV2JYWV5cZFtoZ2VkZ42DjY+Oj4t0a2x6cHZxenaCg3mAe4J/gYGBhYaJiIKmrKyuq66wq4Z/i4OCe3mFfXuAgX51fHR2eHVueW5yb4yPi5WNj5OLbWplanBmbWVobWRmYmFgYGFkYVldYlV/eX1+eHZzeltZU11YVFxXV1pYX15aYVxjY2VhZWFkaIeHkpSVkJSReHh3c3p4fXd7foF7g36AgYOAg4iAgIOrqKeppqempIuFfod8fYB5eX12eHt3fXZyeXJ5cnJvdJaTl4+UjJWScm1ubGlpZW1oaWFkYWFnY2BhY1xfWF9bfnx8dHVydFZSV1lZWVdfV15dW1piX2BeZ2FnaGZnaIqQkZOUlpKYc3hyenl2d3h5eXp7fH1+fn+AgYKDg4SFp6ipqquqqaiGhYSEg4KBgH9/fn18e3p6eXh3dnV0dJSTkpKRkI+ObGtqamloZ2ZlZWRjYmFhYF9eXVxcW1pZeXl4d3Z3d3hYWVpaW1xdXl9fYGFiY2RkZWZnaGhpaoyNjo+PkJGScXJzdHV2dnd4eXp6e3x9fn9/gIGCg4OEpqeoqampqKiGhYSDgoKBgH9+fX18e3p5eXh3dnV1dHOTkpKRkI+ObGxramloaGdmZWRkY2JhYGBfXl1cXFtaenp5eHd3eHlYWVpbXFxdXl9gYGFiY2RkZWZnaGhpamuNjo6PkJGSknJzdHR1dnd4eHl6e3t8fX5/f4CBgoKDpaanqKipqKeFhIODgoGAgH9+fXx8e3p5eHh3dnV1dHOTk5KRkJCPjmxramppaGdnZmVkY2NiYWBgX15dXVxbe3t6eXh4eXlZWltbXF1eXl9gYWJiY2RlZWZnaGhpamuNjo6PkJGRknJyc3R1dXZ3eHl5ent8fH1+f3+AgYKCg6Wmp6eop6aEhIOCgYGAf35+fXx7e3p5eHh3dnV1dHOTk5KRkJCPjmxsa2ppaWhnZmZlZGNjYmFgYF9eXV1cW3x7enl5eXp7WltcXV1eX2BgYWJjY2RlZmZnaGlpamuNjY6PkJCRknFyc3R0dXZ3d3h5eXp7fHx9fn9/gIGBgqSlpqanp6alg4KCgYB/f359fXx7enp5eHd3dnV1dHOUk5KRkZCPj21sa2pqaWhoZ2ZlZWRjY2JhYGBfXl5dXH18e3p6ent7W1xcXV5fX2BhYWJjZGRlZmZnaGlpamtrjY6Pj5CRknFycnN0dXV2d3d4eXp6e3x8fX5+f4CBgaOkpaWmpqWkg4KBgIB/fn59fHx7enl5eHd3dnV1dHNyk5KSkZCPj45sa2tqaWloZ2dmZWVkY2JiYWBgX15eXX59fHt7e3t8XFxdXl5fYGBhYmJjZGRlZmdnaGlpamtrjY6Pj5CRkZJxcnN0dHV2dnd4eHl6ent8fH1+fn+AgKKjpKSlpaWkgoGBgH9/fn19fHt7enl5eHd2dnV0dHNyk5KSkZCQj45sbGtqamloaGdmZmVkZGNjYmFhYF9fXl1+fXx8e3x9XF1dXl9fYGFhYmNjZGVlZmdnaGlpamtrjY6Oj5CQkZJxcnNzdHR1dnZ3eHh5enp7fHx9fn5/f4Cio6OkpaSjo4GAf39+fX18fHt6enl4eHd2dnV0dHNyk5KSkZCQj49tbGtramppaGhnZmZlZGRjY2JhYWBfX15/fn19fH19fl1eX19gYWFiYmNkZGVmZmdoaGlpamtrjY6Oj5CQkZJxcnJzc3R1dXZ3d3h4eXp6e3x8fX5+f4ChoaKio6OioYGAgH9/fn59fHx7e3p6eXh4d3d2dnV0dJCQj46OjYxvb25ubW1sa2tqamlpaGhnZmZlZWRkY2N8e3t6eXl6e2JjY2RlZWZnZ2hpaWpra2xtbW5ub3BwcYiJioqLi4yMd3h4eXp6e3t8fX1+f3+AgYGCg4OEhIWZmpqbm5ubmoeGhoWFhIODgoKBgYCAf39+fn18fHt7eoqJiYiIh4aGdXV0dHNzcnJxcXBwb29ubm1sbGtramp3dnV1dHR0dWlqamtsbG1tbm9vcHFxcnJzdHR1dnZ3d4KDg4SEhYWGfX5+f3+AgYGCg4OEhIWGhoeHiImJiouLk5OUlJSUk4yMi4uKiomJiIiHh4aGhYWEhIODgoKBgYSDg4KBgYCAfHx7e3p6eXl4eHd3dnZ1dXR0c3NycnFxcXBvb25vb3BwcXFyc3N0dHV1dnZ3eHh5eXp6e3t8fH1+fn9/gICBgYKCg4SEhYWGhoeHiIiJiYqLi4yMjY2Ojo+PkJCQj4+Ojo2NjIyLi4qJiYiIh4eGhoWFhISDg4KBgYCAf39+fn19fHx7e3p6eXh4d3d2dnV1dHRzc3JycXFwcG9vcHBxcnJzc3R0dXV2dnd3eHh5eXp6e3t8fH1+fn9/gICBgYKCg4OEhIWFhoaHh4iIiYmKiouLjIyNjY6Oj4+Pj46OjY2MjIuLioqJiYiIh4eGhoWFhISDg4KBgYCAf39+fn19fHx7e3p6eXl5eHh3d3Z2dXV0dHNzcnJxcXBwcXFycnNzdHR1dXZ2d3d4eHl5enp7e3x8fX19fn5/f4CAgYGCgoODhISFhYaGh4eIiImJioqLi4yMjI2Njo6Pjo6NjYyMi4uKiomJiIiHh4aGhYWEhIODgoKCgYGAgH9/fn59fXx8e3t6enl5eXh4d3d2dnV1dHRzc3NycnFxcXJyc3N0dHV1dnZ3d3d4eHl5enp7e3x8fX19fn5/f4CAgYGCg4WGh4l+fn19fHx7enp5eXh4d3d2oqOlpqhzcXBubWtqaWlpaGhnZ2dmp6empqVkY2NiYmJhYWBgYF9fXl5enZycm5tbW1paWllZWFhYV1dWVlZVk5KSkZFTU1RUVVVWVldXWFhZWVpal5eYmJhdXV5eX19gYGFhYmJjY2Rkn5+goKFnZ2hoaWlqamtrbGxtbW5up6eoqKhxcXBwb29vbm5ubW1sbGxroqGhoKBpaWhoZ2dnZmZmZWVkZGRjmJeXlpZhYWBgYF9fXl5eXV1dXFxcjo6NjYxZWVpaW1tcXF1dXl5fX19gkpKSk5OTY2RkZGVlZmZnZ2hoaGlpmZqampubbG1tbm5vb3BwcHFxcnJzoaGhoqKidXV1dHRzc3NycnJxcXFwnJubmpqabm1tbWxsbGtra2pqamlpaZKSkZGQZ2ZmZWVlZGRkY2NjYmJiYYmJiIiIYGBhYWFiYmNjZGRkZWVmZo2Njo6OaWlqampra2xsbG1tbm5vb5SUlZWVcnJyc3N0dHR1dXZ2dnd3eJubm5ycenp5eXl4eHh3d3d2dnZ1dZaVlZWUc3JycnFxcHBwb29vbm5ubY6OjY2Na2tqamppaWloaGdnZ2ZmZoeGhoaFZGRkZWVlZmZnZ2doaGhpaYuLi4yMa2xsbG1tbW5ubm9vb3BwcJKSk5OTc3NzdHR0dXV1dnZ2d3d3eJmampqbm3l5eXh4eHd3d3Z2dnV1dZWVlZSUlHJycXFxcHBwb29vbm5ubY6Ojo2NjWtrampqaWlpaGhoZ2dnZ4eHh4aGhmVlZWZmZmdnZ2hoaGlpaWqLjIyMjWxsbG1tbW5ubm9vb3BwcHGSkpOTk3Jzc3N0dHR1dXV2dnZ3d3eZmZmamnl4eHh3d3d2dnZ1dXV0dHSVlJSUk3JycXFxcHBwb29vb25ubm2Ojo6NjWtra2tqamppaWloaGhoZ2eIiIeHh2ZmZmZnZ2doaGhpaWlqamqMjIyNjWxsbW1tbW5ubm9vb29wcHCSkpKTk3Jyc3NzdHR0dHV1dXZ2dnaYmJiZmXh4d3d3dnZ2dXV1dXR0dHOUlJSUk3JxcXFxcHBwb29vb25ubm6Ojo6OjY1sa2tra2pqamlpaWloaGiJiIiIiIhnZ2dnaGhoaWlpaWpqamqMjI2NjY1sbW1tbW5ubm9vb29wcHCSkpKSk5NycnJzc3N0dHR0dXV1dXZ2l5iYmJh3d3Z2dnV1dXV0dHR0c3NzlJSTk5NxcXFxcHBwcG9vb25ubm5tjo6Ojo1sbGxra2trampqamlpaWloiYmJiYhnaGhoaGlpaWlqampqa2trjY2NjY5tbW1tbm5ubm9vb29vcHBwkpKSkpNycnJyc3Nzc3N0dHR0dXV1lpeXl5d2dnZ1dXV1dHR0dHNzc3Nyk5OTk5NxcXFwcHBwcG9vb29ubm5uj46Ojo5sbGxsbGtra2tqampqamlpioqKioloaGlpaWlqampqamtra2trjY2Njo5tbW1tbm5ubm9vb29vcHBwkZKSkpKScXJycnJyc3Nzc3N0dHR0lpaWlpaWdXV1dHR0dHRzc3Nzc3Jyk5OTk5KScXBwcHBwb29vb29ubm5ubo+Pjo6ObWxsbGxsa2tra2tqampqaouLioqKaWlqampqamtra2tra2xsbI2Ojo6ObW1ubm5ubm9vb29vb3BwcJGSkpKScXFxcnJycnJyc3Nzc3NzdJWVlZaWdHR0dHNzc3Nzc3JycnJycpOSkpKScHBwcHBwb29vb29vbm5ubo+Pj46ObW1tbGxsbGxsa2tra2tra4yLi4uLampqamtra2tra2xsbGxsbI6Ojo6ObW5ubm5ubm9vb29vb29wcJGRkZKScXFxcXFxcnJycnJycnNzc5SUlZWVc3Nzc3Nzc3JycnJycnFxcZKSkpKSkXBwcHBwb29vb29vb25ubo+Pj4+Pj21tbW1tbGxsbGxsbGxra4yMjIyMjGtra2trbGxsbGxsbG1tbY6Ojo+Pj25ubm5ubm9vb29vb29vcHCRkZGRknBxcXFxcXFxcXJycnJycnKUlJSUlHJycnJycnJycXFxcXFxcXGSkpGRkXBwcHBvb29vb29vb29ubm6Pj4+Pj25tbW1tbW1tbW1sbGxsbGyNjY2NjWxsbGxsbGxsbW1tbW1tbW2Pj4+Pj25ubm5ubm9vb29vb29vb2+RkZGRkXBwcHBwcXFxcXFxcXFxcXGTk5OTk3JycXFxcXFxcXFxcXFwcHCRkZGRkXBwcG9vb29vb29vb29vbm6Qj4+Pj25ubm5ubW1tbW1tbW1tbW2Ojo6Ojo5tbW1tbW1tbW1tbW1ubm6Pj4+Pj49ubm5vb29vb29vb29vb2+RkZGRkZFwcHBwcHBwcHBwcHBxcXGSkpKSkpJxcXFxcXBwcHBwcHBwcHBwkZGRkZFvb29vb29vb29vb29vb29vkJCQkI9ubm5ubm5ubm5ubm5ubm1tj4+Pjo9tbW1ubm5ubm5ubm5ubm5uj5CQkJBub29vb29vb29vb29vb29vkJCRkZFvb29wcHBwcHBwcHBwcHBwkZGRkZFwcHBwcHBwcHBwcHBwb29vkZGQkJBvb29vb29vb29vb29vb29vkJCQkJBvb25ubm5ubm5ubm5ubm5uj4+Pj49ubm5ubm5ubm5ubm5vb29vkJCQkJBvb29vb29vb29vb29vb29vkJCQkJCPcHBwcHBwcHBwcHFxcXFxj4+Pj4+PcXFxcXFxcXFxcXFxcnJyjo2NjY2NcnJycnJycnJycnJycnNzjIyMjIyMc3Nzc3Nzc3Nzc3NzdHR0dIuLi4uLdHR0dHR0dHR0dHR1dXV1dYqKioqKdXV1dXV1dXV1dnZ2dnZ2domJiYmJdnZ2dnZ2dnZ3d3d3d3d3d4iIiIiId3d3d3d3d3h4eHh4eHh4eIeHh4eHeHh4eHh4eXl5eXl5eXl5eYaGhoaGeXl5eXl6enp6enp6enp6eoWFhYWFenp6e3t7e3t7e3t7e3t7e4SEhISEe3t8fHx8fHx8fHx8fHx8fIODg4ODfH19fX19fX19fX19fX19fYKCgoKCfn5+fn5+fn5+fn5+fn5+foGBgYGAf39/f39/f39/f39/f39/f4CAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICFjJOZn6Wfo6aoq62ur7Cwr66tq6mmz87MycaNh4J8dW9oY11XUkxGQDs2c29saWYjIR8eHR0dHh8gIiQnKi0xdXl+g4hOU1leZGpwdnyCh42SmJ2i4uTl5ueqqqmop6akop+cmZWRjYmEu7awq6VkXlhTTUdCPDcyLSgjHxoWT09PT1AXGRocHiEkJyouMjY6P0NIhouQlZpnbXJ3fYKHjJGVmp6jp6qu5ubm5eSsq6mnpKKfnJmWko6KhoJ9rqmkn5phXFdTTklFQDw3My8rKCQhUlJSU1QjJCYoKiwuMTQ3Oz5CRUlNg4eLj5SYbHB1eX6Ch4uPk5ebn6Om2NjY19fWpqWjoqCenJqYlZKPjImGsKyppaGdbGhkYFxXU09LR0RAPDg1XV1dXV1dMjM0NTY3OTo8PkBCREdKTHl8f4KFX2Nmam5xdXl9gISIjJCTl8DAwMHBmZmZmZiYl5aWlZSSkZCOjLGvrKqof316d3RxbmtoZWJeW1hUUXR0dHNzT05OTk5OTk5PT09QUFFSU3d4eXp7WlxeYGFkZmhqbW9ydHd6fZ+fn5+ffX19fn5+fn5+fn5+fn5+fZ6enp2de3p6eXh3dnV0cnFwbmxraYqLjI2NbW5ub29wcHFxcXJycnJycpSUlJSUc3N0dHR0dXV2dnd3eHh5epuZl5WTcG5ta2loZ2VkY2JhX19eXX18fHt7elhYV1dWVlZVVVVUVFRTU3R3enx/gWJlZ2psbnFzdXd5e31/gaSmp6mqrIyOj5CSk5SVlpeYmZqbnL68ube1s4+NioiGg4F+fHp3dXNwbmuKiIaDgV5bWVdVU1FPTUtJR0VDQkBiY2RmZ0dJSktNT1BSVFVXWVtcXmCDhYeJi2xucHJ0d3l7fX+BhIaIioytrayrq4mIh4eGhYSDg4KBgH9+fXycm5qZmHZ0c3Jxb25ta2poZ2ZkY2GCg4WGh2doaWprbG1ub3BwcXJzdHWXmJiZmnp6e3x9fn5/gIGCgoOEhYanpaOhn3x6eXd1c3Jwbm1raWhmZWODgYB+fVpZV1ZVU1JRUE5NTEtKSUdoamxtb09RU1RWWFpbXV9hYmRmaGmMjpCSk5V2eHl7fX+AgoSGh4mLjY6xsK+urayKiIeGhYSDgoGAf359e3qamZiXlZRycG9ubWtqaWdmZWNiYV9/gIGDhIVlZmdoamtsbW5vcHFyc3R1mJmam5x8fX5/gIGCg4SFhoeIiYqLqqmnpqSBgH59e3l4dnVzcnBvbWxqioiHhYRhYF5dW1pYV1ZUU1FQT01Mbm9wcXNTVFVWWFlaW11eX2BiY2RmiJKUlZZ2d3l6e3x+f4CBg4SFh4iJqqmnpqWCgYB/fXx7enh3dnVzcnFvj46NjIpoZ2VkY2JgX15cW1pZV1ZVdnd5entbXF5fYGFjZGVnaGlqbG1ukZKTlJZ2d3h6e3x9f4CBgoSFhoeJqqmop6WDgoB/fn17enl3dnV0cnFwkI+NjItoZ2ZkY2JhX15dXFpZWFZVdnd4eXt8XF1fYGFiZGVmZ2lqa21ukJKTlJWXd3h5enx9foCBgoOFhoeIq6mop6akgoF/fn18enl4d3V0c3Fwb4+OjIuKZ2ZlZGJhYF5dXFtZWFdWVHd4eXp8XF1eX2FiY2VmZ2hqa2xtb5GSlJWWdnh5ent9fn+AgoOEhYeIiaqpp6algoGAfn18e3l4d3Z0c3Jxb4+OjYuKaGZlZGNhYF9eXFtaWFdWVXZ3eXp7W11eX2BiY2RlZ2hpa2xtbpGSk5WWdnd4ent8fn+AgYOEhYaIiaqpqKalg4GAf358e3p5d3Z1c3JxcJCOjYyLaGdmZGNiYF9eXVtaWVhWVXZ3eHp7W1xdX2BhY2RlZmhpamttbpCSk5SWdnd4eXt8fX6AgYKDhYaHiaupqKelpIKAf359e3p5eHZ1dHNxcJCPjYyLimdmZWNiYWBeXVxaWVhXVXV3eHl7fFxdXmBhYmNlZmdpamtsbpCRk5SVlnZ4eXp8fX5/gYKDhIaHiImqqKempYKBgH59fHp5eHd1dHNycG+Pjo2LimdmZWRiYWBfXVxbWlhXVlR2eHl6e1xdXl9hYmNkZmdoaWtsbW+RkpSVlnZ3eXp7fH5/gIKDhIWHiImqqaempYKBgH99fHt6eHd2dXNycW+Pjo2MimhnZWRjYmBfXlxbWllXVlV2d3l6e1tcXl9gYWNkZWdoaWpsbW6RkpOUlnZ3eHp7fH1/gIGChIWGh4mqqainpYOCgH9+fHt6eXd2dXRycXCQjo2Mi2hnZmRjYmFfXl1cWllYVlV2d3h5e3xcXV9gYWJkZWZnaWprbW6QkpOUlZd3eHl6fH1+gIGCg4WGh4irqainpqSCgX9+fXx6eXh2dXRzcXCQj46Mi4pnZmVjYmFgXl1cW1lYV1ZUd3h5enxcXV5gYWJjZWZnaGprbG1vkZKUlZZ2eHl6e31+f4CCg4SGh4iJqqmnpqWCgYB+fXx7eXh3dnRzcnFvj46Ni4poZmVkY2FgX15cW1pYV1ZVdnd5entbXV5fYGJjZGVnaGlrbG1ukZKTlZZ2d3h6e3x+f4CBg4SFhoiJqqmopqWDgYB/fnx7enh3dnVzcnFwkI6NjIpoZ2VkY2JgX15dW1pZWFZVdnd4entbXF5fYGFjZGVmaGlqa21ukJKTlJZ2d3h5e3x9f4CBg4SFhoiJqqmnpqWjg4GAf358e3p5eHZ1dHNyjo2MiomIaWhnZWRjYmFfXl1cWllYc3R1dnh5X2BiY2RlZ2hpa2xtb3BxjI6PkJGSe3x9foCBgoSFhoiJioyNjqWjoqGfh4aFhIKBgH99fHt6eXd2dYmIhoWEbmxramloZmVkY2FgX15dW29xcnN0Y2RlZ2hpa2xtb3Bxc3R1d4mKi42OfoCBgoSFhoiJioyNjpCRkqGgnp2cjIuJiIeGhIOCgYB+fXx7eoWEg4GAcnFwb21sa2poZ2ZlZGJhYGtsbW9wZ2hpa2xtb3BxcnR1dnh5eoSGh4iJgoSFhoiJioyNjo+RkpOVlp2cmpmYkI+OjYuKiYiHhYSDgoF/foGAf318d3Z0c3JxcG5tbGtpaGdmZWZnaWpra2xtbnBxcnR1dnh5enx9foCBgoSFhoeJiouMjo+QkZOUlZeYmZqZmJaVlJKRkI+NjIuKiIeGhYOCgX9+fXx6eXh3dXRzcnBvbmxramlnZmVmZ2lqa2xub3Bxc3R1dnh5enx9fn+BgoOEhoeIiYuMjY+QkZKUlZaXmZqZmJeVlJOSkI+OjYuKiYeGhYSCgYB/fXx7enh3dnRzcnFvbm1samloZmVmZ2hpa2xtb3BxcnR1dnd5ent8fn+AgoOEhYeIiYqMjY6PkZKTlZaXmJqamJeWlJOSkY+OjYyKiYiHhYSDgYB/fnx7enl3dnV0cnFwbm1sa2loZ2ZlZ2hpamxtbm9xcnN0dnd4ent8fX+AgYKEhYaHiYqLjY6PkJKTlJWXmJmamZeWlZSSkZCOjYyLiYiHhoSDgoF/fn17enl4dnV0c3Fwb25sa2poZ2ZlZmdpamttbm9wcnN0dXd4eXp8fX6AgYKDhYaHiIqLjI2PkJGTlJWWmJmamZiWlZSTkZCPjoyLiomHhoWDgoGAfn18e3l4d3Z0c3Jwb25ta2ppaGZlZmdoamtsbW9wcXN0dXZ4eXp8f4GDe3x8fHx9fX19fn5+oaOlqICAgICBf317eHZ0cm+wr66saWhnZWRjYmFfXl1cWpqZl5ZUU1JRT05NTEtJSEeFhYaIiUtMTk9QUlNUVVdYWZmam5xgYWNkZWdoaWpsbW5wrq+wsXZ4eXp7fHt5eHd2dHOtrKqpbWxraWhnZmVjYmFgmJeWlFpYV1ZVU1JRUE9NTEuCgYKETU5QUVJUVVZXWVpbXZWWl5hjZWZnaGprbG5vcHKoqqusrXp7fH1/gH99fHt6eKuqqadycXBvbWxramlnZmVklZSSkV5cW1pZV1ZVVFNRUE9/fX6AUFJTVFVXWFlbXF1fkJGSk5RnaGlqbG1ucHFydHWkpqeoe31+f4GCg4OBgH9+fKinpaR2dXRzcXBvbm1ramlokpCPjmJgX15dW1pZWFZVVH17enpSVFVWV1laW11eX2FijI2Oj2hqa2xub3Byc3R2d3igoqOkf4CBg4SFh4eFhIOCpqWjoqF6eXh3dXRzcnBvbm2Qjo2MZ2VkY2JhX15dXFpZWHl4d3ZVV1hZW1xdX2BhY2RliImKi2xtbm9xcnN0dnd4eZydnqCAgYKEhYaHiYmIh4WEpKOioH59e3p5eHZ1dHJxcG+PjYyLaGdmZWNiYV9eXVxaenl4d3ZWV1hZW1xdXmBhYmSGh4mKamtsbm9wcXN0dXd4eZydnp9/gYKDhIaHiIqIh4aFpKOioX59fHp5eHd1dHNycJCPjoyLaWdmZWRiYWBfXVxbe3l4d1RVV1hZWlxdXl9hYmOGh4iJamtsbW9wcXJ0dXZ3eZucnp9/gIKDhIWHiImJh4ampaSigH99fHt5eHd2dHNycZGPjo1qaWhmZWRjYWBfXlxbe3p5d1VVVldZWltdXl9gYoSFh4iJaWpsbW5wcXJzdXZ3mpucnX1/gIGDhIWGiImJiIempaSjgH9+fHt6eXd2dXRycZGQjo1raWhnZmRjYmFfXl19e3p5eFVVVldYWltcXV9gYYSFhodoaWprbW5vcHJzdHV3mZqcnX1+gIGCg4WGh4iJiIenpqSjgX9+fXt6eXh2dXRzk5GQj2xramhnZmVjYmFgXl19fHp5V1VUVVdYWVtcXV5gYYOFhodnaGprbG5vcHFzdHWYmZqbnX1+f4GCg4SGh4iJiainpqWCgYB+fXx7eXh3dnRzk5KQj21ramloZmVkY2FgX119fHt6V1ZVVVZYWVpbXV5fgoOEhmZnaGlrbG1ucHFydHWXmZqbe3x+f4CBg4SFh4iJiamopqWDgYB/fXx7enh3dnWVk5KRj21samloZ2VkY2JgX39+fHtZV1ZVVVZXWVpbXF5fgYOEhWVmaGlqbG1ub3Fyc3SXmJmbe3x9f4CBgoSFhoeJqqmop6WDgoB/fn17enl3dnWVlJKRb21sa2poZ2ZkY2JhX39+fXxZWFdVVFZXWFlbXF1fgYKEhWVmZ2lqa2xub3Byc5WXmJl5enx9fn+BgoOFhoeIq6qop4WDgoF/fn18enl4d3WVlJORb25sa2ppZ2ZlZGJhgYB+fXxZWFdWVFVXWFlaXF1/gYKDY2RmZ2hqa2xtb3BxcpWWl5l5ent9fn+AgoOEhYeIqqqpp4WEgoGAf318e3l4d5eWlJNxb25tbGppaGZlZGNhgYB/fltaWVdWVVVWV1laW11/gIKDY2RlZ2hpamxtbnBxk5WWl5h4ent8fX+AgYOEhYapqqqphoWEg4GAf358e3p5d5eWlZNxcG5tbGtpaGdmZGNigoB/fltaWVhWVVVWV1haW31/gIGCY2RlZmhpamttbm9wk5SVl3d4eXt8fX6AgYKDhYaoqquph4aEg4KBf359e3p5eJiWlZRxcG9ubGtqaGdmZWODgoGAXVxbWVhXVVRVV1hZW31+gIFhYmNlZmdoamtsbm9wk5SVlnZ4eXp7fX5/gYKDhKeoqauqh4aFg4KBgH59fHt5mZiXlXNycG9ubWtqaWhmZWSEgoGAXVxbWlhXVlVVVlhZWn1+f4BhYmNkZmdoaWtsbW6RkpOVlnZ3eXp7fH5/gIGDhKaoqaqJiIaFhIOBgH99fHt6mpiXlnNycXBubWxqaWhnZWSEg4KAXlxbWllXVlVVVldZe3x+f19gYWNkZWdoaWpsbW6RkpOUdHZ3eHp7fH1/gIGChKanqaqJiIeFhIOCgH9+fXubmpmXlnRycXBvbWxramhnZoaEg4JfXl1cWllYV1VUVldYe3x9fl9gYWJkZWZnaWprbG6QkZOUdHV3eHl6fH1+f4GCpKanqIiKiIeGhIOCgX9+fXycmpmYdXRzcXBvbmxramlnZoaFg4JgXl1cW1lYV1ZUVVd5enx9fl5fYWJjZWZnaGprbI+QkZJydHV2eHl6e31+f4CCpKWnqIiJiYeGhYSCgYB/fXycm5mYdnRzcnFvbm1samloiIaFhINgX15cW1pZV1ZVVVZ5ent9XV5fYGJjZGVnaGlqbI6QkZJyc3V2d3h6e3x9f4CBpKWmqIiJiYiGhYSDgYB/fp6cm5p3dnVzcnFwbm1sa2loiIeFhGJgX15dW1pZWFZVVVZ4ent8XF1fYGFjZGVmaGlqjY6PkJJyc3R2d3h5e3x9foCio6WmhoeJiYiHhoSDgoB/fp6dm5p4dnV0c3Fwb21sa2poiIeGhWJhYF5dXFpZWFdVVHd4eXt8XF1eYGFiZGVmaGlqjI2Oj3FydHV2eHl6e31+f4GgoqOkh4mKi4qJiIeFhIOCnZybmZh7eXh3dnRzcnFwbm2HhoSDZ2ZlY2JhYF9dXFtaWHJ0dXZeYGFiZGVmaGlqbG1uh4iJi3V2d3l6e31+f4GCg5ucnZ6fi42Oj4+OjIuKiYiGmZiXlYB/fn17enl4d3V0c3KDgoB/bGppaGdmZGNiYV9eXW5vcHFiZGVmaGlqbG1ub3GBgoSFd3l6e31+f4GCg4WGh5aXmJqOj5CSk5SSkZCPjYyLlZSTkoWEgoGAf358e3p5eIB/fnx7cG9ubWtqaWhnZWRjamlqbGVmZ2lqa21ub3Fyc3V9fn+Ae31+f4GCg4SGh4iKi5GTlJWSk5SWl5iXlpSTkpGTkpCPjoqIh4aFg4KBgH99fH17enl2dXRycXBvbmxramlnZmVmZ2hqa2xub3Bxc3R1dnh5ent9fn+BgoOEhoeIiYuMjY6QkZKUlZaXmZqZmJeVlJOSkI+OjYuKiYeGhYSCgYB/fXx7enh3dnRzcnFvbm1samloZ2VmZ2hpa2xtbnBxcnR1dnd5ent8fn+AgYOEhYeIiYqMjY6PkZKTlJaXmJqamJeWlZOSkY+OjYyKiYiHhYSDgoB/fnx7enl3dnV0cnFwb21sa2loZ2ZlZ2hpamxtbm9xcnN0dnd4ent8fX+AgYKEhYaHiYqLjY6PkJKTlJWXmJmamZeWlZSSkZCPjYyLiYiHhoSDgoF/fn18enl4dnV0c3Fwb25sa2ppZ2ZlZmdpamtsbm9wcnN0dXd4eXp8fX5/gYKDhYaHiIqLjI2PkJGSlJWWmJmamZiWlZSTkZCPjoyLiomHhoWDgoGAfn18e3l4d3Z0c3Jwb25ta2ppaGZlZmdoamtsbW9wcXJ0dXZ4eXp7fX5/gIKDhIWHiImLjI2OkJGSk5WWl5iamZiXlpSTkpGPjo2LiomIhoWEg4GAf358e3p4d3Z1c3JxXHJ9cV90aVJbVFdOcYBipJ2gZGBTcV5pcGt8fmKZiKNdTWNKa2t5WnltbI+2sWJ0fXhdY3NseWNuvLuoe3t7enpjVFpnfF6WsJN5gFBbaFFKT2tiVKJ/gkVTXVoxXVE/MVFXfpWHP0pXVEpCQVlEVmaQf56OWWZjZFhaanJqcJ+4wbWIc3SWdZyQmJR8qMa6n31obIBbg393cnmlh52fUGJbS0NMXDxWPXWDkYhDSkxHQDtQN1hEkHx8nk1jVFdad1lmbHyflK60fHqAcXCBcW2LiqOfpcBpcG2CdXVof2J3gZ+brH5nc1ZecG1mb1JXjZidXVVvclZacXFXX2uHhZFQSmVmS1dealVZY36VflNOXVZnWWBtWmZunqCQZ2ttZHFjd2BgbnKlsJhpgHmAf4uAkXF/iaSktIF3hXSAenl2bGxln6ehampiX2FpVVZRXmSEjnR3RFtbWUdCQVZWTXhzgX5KVVNlVFZeWGBgjoyUn3hpenF3f4B8fIWmoLanmIuCmYWJg417eaOXoad4d36DZ2hpa25rhYJ+lFlsY25eX1heUVl6h3d2UF1SWEtVVGVSaHyDiIBwZnJ1bmtufGh7bJSYjXJ8g3t1d4N5f4WAmpmYiYqAf3mBfYOEgH2gl6R3cINrbXx1b3BobZGJjHBzcGpmZW5ob1phg36IYl9jVmNRUGNWYF6BhYZnYFxXXWBpY2NoaIGLj3FncGt7eHl/fX52qpymepCRho6SiYuTf4yppKSthIV9dX6AgXBzcJaJi5VsYm5ra2FeXFpUdnZxelBLSFlXWFJdVVqDdn+CW1pfXGVxb2hmbpmanpF8eYByfnV9f4eGoqCvrI6HjpKFjIiIhoCaoKObeHFvcHhxd3JxdIyIkY9mbGxoZ2NgX2diWIWDgVViV1tZW1RiZWVmhIiIXWdoZW9jbXBucXWPj5VycXh4b3l6c350dpyao3qHhoSEhIh8g4N/oJmidnSAdXhxeHJ8em+VjZJsa2poamhpZl5fYoKCfF1fWVRNW1ZWUVJge3yDZGRdZWBkaGdicGeOjYuQbXlzeH13fXx5gKmiq6WJkImNiYiGhYaJpp6ipniAen1+eHRwdHWSipGKY2hiYGFdYV5YXXd8enlTVU5PU1FRXV9gfYF+iGdmY2pobmltcHSPl5OVdnh2eX93d3uCf6CjoKKBgoyIgot/gIJ7ep+YmXp2fHRwdm91bm1qkJCNb2drY2xoaWNlYV9/e4JcXFRWVFdeXVtfYn+Ef2dlaWprZWhmaWxpj5KScW94cHh3dXV+e32cpaCFh4WGiIaJiImHh6OmoIJ6gH14dnV0cnFwkI+Na2poZ2ZlY2JhX15+fXx6WFdVVFZXWFlbXH6AgYJiZGVmZ2lqa2xukJGTlHR1d3h5enx9fn+io6SmhoeIioiHhoWDgqKhn558enl4d3V0c3JwkI+OjGppZ2ZlZGJhYF9/fXx7WFdWVFVXWFlaXH5/gYJiY2RmZ2hqa2xtb5GSlHR1dnd5ent9fn+Ao6SlhYeIiYmHhoWEgoGhoJ98e3p4d3Z0c3Jxb4+OjWppaGdlZGNhYF9efnx7WVdWVVVWV1laW1x/gIFiY2RlZ2hpamxtbpGSk3N1dnd4ent8fX+AoqSlhYaIiYmIh4WEg4GhoJ+ee3p5d3Z1dHJxcJCOjYxpaGdmZGNiYV9efn17elhWVVVWV1haW1x/gIGCYmRlZmhpamttbpCSk5R0dXd4eXt8fX6AoqOlpoaHiImIh4aEg4KioZ+efHp5eHZ1dHNxcJCPjoxqaWdmZWNiYWBeXX18e1hXVlRVV1hZWlxdgIGCYmNlZmdoamtsbm+Rk5R0dXZ4eXp7fX5/gaOkpoaHiImJh4aFg4KBoaCefHt5eHd2dHNycG+Pjo1qaWhmZWRjYWBfXX18e1hXVlVVVlhZWltdf4CCYmNkZmdoaWtsbW6RkpOVdXZ3eXp7fH5/gKOkpaaGiImJiIaFhIOBoaCfnXt6eHd2dXNycXCQjo2MaWhnZWRjYmBfXn59e3pXVlVVVldZWltcf4CBg2NkZWZoaWpsbW6RkpOUdHZ3eHl7fH1/gKKkpaaGh4mJiIeFhIOCgKCfnnt6eXh2dXRycXBvj42MamhnZmVjYmFfXl19fHpYV1VUVldYWVtcXYCBgmJkZWZnaWprbG5vkZOUdHV3eHl6fH1+f4GjpKaGh4iKiIeGhYOCgaGfnnx6eXh3dXRzcnBvj46MamlnZmVkYmFgX119fHt5V1ZUVVdYWVpcXX+BgoNjZGZnaGprbG1vkZKUlXV2d3l6e31+f4CjpKWnh4iJiYeGhYSCgaGgn517eXh3dnRzcnFvj46NjGloZmVkY2FgX15+fHt6V1ZVVVZXWVpbXX+AgoNjZGVnaGlqbG1ucJKTlXV2d3h6e3x9f4CBpKWmhoiJiYiHhYSDgYCgn557enl3dnV0cnFwbo6NjGloZ2ZkY2JhX15dfXt6WFZVVVZXWFpbXF2AgYJiZGVmaGlqa21ub5KTlHR1d3h5e3x9foCBo6WmhoeIiYiHhoSDgoGgn56denl4dnV0c3Fwb4+NjItoZ2ZlY2JhYF5dfXx6eVdVVFVXWFlbXF2AgYKDY2VmZ2hqa2xub5GTlJV1dnh5ent9fn+Bo6Smp4eIiYmHhoWDgoGhoJ6de3l4d3Z0c3Jwb4+OjYtpaGdlZGNiYF9eXXt6eVhXVlZXWVpbXV5ff4CBZWZnaWprbW5vcHKQkZJ3eHp7fH5/gIKDhKGipImLjIyLioiHhoWDnJuaf318e3p5d3Z1dHKKiYdubGtqaWhmZWRjYXh2dV1bWlpbXV5fYWJjenx9aGprbG5vcHJzdHaLjY6PfH5/gIKDhIWHiJyen6CPkJGPjo2Mi4mImZeWlYKBgH59fHt5eHeGhYOCcXBvbWxramhnZnRycXBgX15fYWJjZGZndnd4eW5vcHJzdHZ3eHqHiImLgIGDhIWHiImLjJiZmpyTlJWUk5KQj46Ni5OSkYeFhIOCgX9+fXx6gYB+dnRzcnFvbm1sa2lubWxlY2JjZGZnaGprbHJ0dXJzdHZ3eHl7fH1/g4WGhIWHiImLjI2PkJGVlpeWmJmZl5aVlJKRkI+OjYuKiYiGhYSCgYB/fXx7enh3dnVzcnFvbm1samloZ2VmZ2hpa2xtbnBxcnN1dnd5ent8fn+AgYOEhYaIiYqMjY6PkZKTlJaXmJmamJeWlZOSkY+OjYyKiYiHhYSDgoB/fnx7enl3dnV0cnFwb21sa2loZ2ZlZmhpamxtbm9xcnN0dnd4eXt8fX+AgYKEhYaHiYqLjI6PkJKTlJWXmJmamZeWlZSSkZCPjYyLioiHhoSDgoF/fn18enl4d3V0c3Fwb25sa2ppZ2ZlZmdpamtsbm9wcXN0dXd4eXp8fX5/gYKDhIaHiIqLjI2PkJGSlJWWmJmamZiXlZSTkZCPjoyLiomHhoWEgoGAfn18e3l4d3Z0c3Jxb25ta2ppaGZlZmdoamtsbW9wcXJ0dXZ3eXp7fX5/gIKDhIWHiImKjI2OkJGSk5WWl5iamZiXlpSTkpGPjo2MiomIhoWEg4GAf358e3p5d3Z1c3JxcG5tbGtpaGdmZWdoaWpsbW5wcXJzdXZ3eHp7fH1/gIGDhIWGiImKi42Oj5CSk5SWl5iZmpmXlpWTkpGQj4+Jh4SCgH17eY2NjHBua2lnZGJgiopZV1VSUE5LSYeHhkVGSElKTE1OkZJSVFVWV1laW52foGFiY2VmZ2lqq6xub3Byc3R2d7e4unp4d3Z1c3JxrqxtbGtqaGdmZaGfnmBfXVxbWllXkpFUUlFQT05MS4WEg0hKS0xOT1BSjY6QV1hZW1xdX5mbnGRlZ2hpamxtp6ipcnR1dnh5eny0tn58e3p5d3Z1qqmocG9ubGtqaWicm2RjYWBfXl1bj46MVlVUU1JQT06Bf0xNTlBRUlRViYqMWltdXl9hYmOXmGdpamtsbm9wo6Sldnd4ent8fX+wsoKAf359e3p5p6aldHNycG9ubWyZl5ZnZWRjYmBfjIqJWllYV1VUU1J9fHtQUlNUVldYhYaIXV9gYWNkZWeTlJVsbW5wcXJ0daCheXp7fX5/gYKsrq6Eg4KBf359fKOheHd2dHNycW+WlJNraWhnZmRjYoeGXl1cW1lYV1Z6eXdUVVZXWVpbXYOEYWJjZWZnaGqPkJFvcHJzdHZ3eJydfH1/gIGDhIWoqquIh4aFg4KBgKCenXt5eHd1dHOTkpBubWtqaWhmZYWEgmBfXVxbWlhXd3ZVVlhZWltdXoGCg2NkZmdoaWtsjpBwcXJ0dXZ3eZucnn5/gIGDhIWHqaqJiIaFhIKBgKCfnXt6eHd2dXNykpFubWxqaWhnZYWEg2BfXlxbWllXd3ZVVldZWltcXoCBg2NkZWdoaWpsjo9vcXJzdHZ3eJucnX1/gIGChIWGqaqqiIeFhIOCgKCfnnt6eXd2dXRykpGQbWxraWhnZmSEg2FfXl1cWllYeHZ2VldYWltcXV+BgmJkZWZnaWprjo+QcHJzdHV3eHmcnX1+gIGCg4WGqKqriIeGhIOCgX+fnnx6eXh3dXRzk5GQbmxramlnZmWFg2FgXl1cW1lYeHd2VVdYWVpcXV6BgoNjZWZnaGprjY+QcHFydHV2eHmbnZ5+f4CCg4SFqKmriYeGhYSCgYCgnp17eXh3dnRzcpKQbm1ramloZmWFhINgX15cW1pYV3d2VVZYWVpbXV6AgoNjZGVnaGlrbI6QcHFyc3V2d3ibnJ1+f4CBg4SFhqmqiYiGhYSDgYCgn557enl3dnVzcpKRbm1sa2loZ2aFhINgX15dW1pZWHh2dlZXWFpbXF6AgYNjZGVmaGlqa46PkHFyc3R2d3h5nJ19foCBgoSFhqmqq4iHhoSDgoB/n557enl4dnV0c5KRkG1sa2poZ2ZlhYNhYF5dXFpZWHh3dVZXWFlbXF1egYJiY2VmZ2lqa46PkHBxc3R1dnh5m519fn+BgoOEhqipq4iHhoWDgoGAoJ6denl4d3V0c5OSkG5ta2ppZ2ZlhYSCYF9dXFtaWHh3dlVWWFlaXF1egYKDY2RmZ2hpa2yOkHBxcnR1dnd5m5yefn+AgoOEhYepqomIhoWEgoGAoJ+de3p4d3Z1c3KSkW5tbGppaGdlhYSDYF9eXFtaWVd3dlVWV1laW1xegIGDY2RlZ2hpamyOj29xcnN0dnd4m5ydfX+AgYKEhYapqqqIh4WEg4KAoJ+ee3p5d3Z1dHKSkZBtbGtpaGdmZISDYV9eXVxaWVh4dnZWV1haW1xdX4GCYmRlZmdpamuOj5BwcnN0dXd4eZydfX6AgYKDhYaoqquIh4aEg4KBf5+efHp5eHZ1dHOTkZBubGtqaWdmZYWDYWBeXVxbWVh4d3ZVV1hZWlxdXoGCYmNlZmdoamuNj5BwcXN0dXZ4eZudnn5/gIKDhIaoqauJh4aFhIKBgKCenXt5eHd2dHNykpBubWtqaWhmZYWEg2BfXlxbWlhXd3ZVVlhZWltdXoCCg2NkZWdoaWtsjpBwcXJzdXZ3eJucnn5/gIGDhIWGqaqJiIaFhIOBgKCfnXt6eHd2dXNykpFubWxraWhnZYWEg2BfXl1bWllYd3Z2VldYWltcXoCBg2NkZWZoaWprjo+QcXJzdHZ3eJucnX1+gIGChIWGqaqriIeFhIOCgH+fnnt6eXh2dXRykpGQbWxramhnZmWFg2FfXl1cWllYeHd2VldYWVtcXV6BgmJkZWZnaWprjo+QcHFzdHV3eHmcnX1+f4GCg4SGqKmriIeGhYOCgYCfnnx6eXh3dXRzk5KQbm1ramlnZmWFhIJgX11cW1pYeHd2VVZYWVpcXV6BgoNjZGZnaGlrbI6QcHFydHV2d3mbnJ5+f4CCg4SFh6mqiYeGhYSCgYCgn517enh3dnRzcpKRbm1samloZ2WFhINgX15cW1pZV3d2VVZXWVpbXF6AgYNjZGVnaGlqbI6Pb3Fyc3V2d3ibnJ19f4CBgoSFhqmqiYiHhYSDgoCgn557enl3dnV0cpKRkG1sa2loZ2aGhINhX15dXFpZWHh2dlZXWFpbXF1fgYJiZGVmaGlqa46PkHByc3R1d3h5nJ19foCBgoOFhqiqq4iHhoSDgoF/n558enl4dnV0c5ORkG5sa2ppZ2ZlhYNhYF5dXFtZWHh3dVVXWFlaXF1egYJiY2VmZ2hqa42PkHBxc3R1dnh5m52efn+AgoOEhqipq4mHhoWDgoGAoJ6de3l4d3Z0c5OSkG5ta2ppaGZlhYSDYF9dXFtaWFd3dlVWWFlaW11egIKDY2RmZ2hpa2yOkHBxcnN1dnd5m5yefn+AgYOEhYapqomIh4WEg4KBn56dfHp5eHd2dHORkHBubWxraWhnhIKBYmFgXl1cW1p1dFdYWltcXl9gfX+AZWdoaWtsbW+LjI10dXd4eXt8l5iZgYKEhYaIiYqkpqaMi4qJiIaFhJqZgH9+fXt6eXiNjIpzcnBvbm1san99Z2ZkY2JhX15xcG9cXV9gYWNkZXp7aWtsbW9wcXOGh4l4eXp8fX6AgZSVhYaIiYqMjY6goaKRkI+NjIuKiZaVhYSCgYB/fnyJiId4dnV0c3Fwb3t5eGppaGZlZGNubGtgYWNkZWdoaXV3eG9wcXJ0dXaCg4R8fX6AgYKEhY+QkYqMjY6PkZKTnJ6WlJOSkZCOjZKRkIiHhoWDgoGAhIN8e3p4d3Z1dHd1dG9ubGtqaWdmaGdkZWdoaWtsbXFyc3J0dXZ4eXp8fn+AgYKEhYaHiYqMjY6PkZKTlJaXmJmamJeWlZOSkZCOjYyKiYiHhYSDgoB/fn17enl3dnV0cnFwb21sa2poZ2ZlZmhpamttbm9xcnN0dnd4eXt8fX6AgYKEhYaHiYqLjI6PkJGTlJWXmJmamZiWlZSSkZCPjYyLioiHhoWDgoF/fn18enl4d3V0c3Jwb25sa2ppZ2ZlZmdpamtsbm9wcXN0dXd4eXp8fX5/gYKDhIaHiIqLjI2PkJGSlJWWl5mamZiXlZSTkpCPjoyLiomHhoWEgoGAf318e3l4d3Z0c3Jxb25tbGppaGZlZmdoaWtsbW9wcXJ0dXZ3eXp7fH5/gIKDhIWHiImKjI2Oj5GSk5WWl5iamZiXlpSTkpGPjo2MiomIhoWEg4GAf358e3p5d3Z1c3JxcG5tbGtpaGdmZWdoaWpsbW5vcXJzdXZ3eHp7fH1/gIGChIWGiImKi42Oj5CSk5SVl5iZmpmXlpWUkpGQjo2Mi4mIh4aEg4KBf359e3p5eHZ1dHNxcG9ubGtqaGdmZWZoaWprbW5vcHJzdHV3eHl7fH1+gIGCg4WLk5uioqessLW4vL/CxMbm6enEwr67trKtqKKclsrFwHt0bWdhW1ROSEI9eXRvKCQgHBkWFBEQDg1NTU8SFRkdISYrMDU6QIWLkFddY2ludHl+g4iNz9PXnJ+ipKeoqqurrKzo6OWloZyYlI+KhYB6daumoZtbVlFMR0M/OzczamdkYiYkIiEgHx8fHx9ZWlxgKzA0OT1CR0xRVpOXnKFuc3d7gISHi46Sy87Q0p6foaKjpKSkpKTZ2NbSmZWRjYmFgHx3c6OempVdWVVRTUpGQ0A9bWpoZjEvLi0sKyoqKioqXF1gMjY5PUFFSU1RVVmOkpZqbnJ2en2BhIiLjsDCxZianJ6foaKjpKSl09PQoJ2al5OQjYmGgn6opKBwbGhkYV1aVlNQTXVycEE/PDo4NjUzMTAvWVhaMTM2ODs9QENGSUx5fH9aXWBkZ2tucnV5fKirrrGMj5KUl5mcnqCiy83My6OioJ+dm5mXlZO2tLGuhoOBfnt4dXJua42KhoNcWVZTUE1KSEVCY2FgYD4+Pz9AQUJDREZpa2xuTlBSVFdZW15gY4eJjI9wc3Z5fH+BhIeKrrGyspGSkpKSkpGRkZCQsbCvjYyLiomIh4WEgoGgnp15d3VzcW9samhlY4GAgF9eXl5eXl5eXl5ef39/Xl5eXl9fX2BgYWGDhIVlZmdoaWprbW5wcZSVlHJycXBwb29vbm5uj46ObW1tbGxsbGxsbGuNjIxrampqamlpaGhnZ4eHiYtrbW5wcXN0dnd4mpydnn1+f4CBgoKDhISmp6enh4eIiIiJiYmKiqysqqeEgoB+e3l3dXNxkI6MimdlY2JgXlxbWVh3dnRzUE9OTUtKSUhHRmZlZmhJSkxOUFFTVVdZfH6AgmNlZ2lrbW9xc3V3mpyef4GDhYeIioyOkJK1tbSSkZCPj46NjIuKiamnpoSDgYB/fnx7eXh2lpWTcG9tbGpoZ2VjYWB/f4BfYGFhYmNjZGVlZoiJiWlpamtsbG1ubm9wkpOUc3R1dnd3eHl6e3yenp16eXd2dHNycG9ubIyLiolmZWRjYmFgX15dfXx7elhXVlVUU1JRUE9wcHFzU1VXWVpcXl9hY4aHiYtrbW9wcnR1d3l6nZ+gooKEhYeJioyNj5CztLOykI6NjIuKiYiGhaWko6F/fnx7enl3dnRzk5KQj2xraWhmZWNiYV9efX5/X2BhYmNkZWZnaGmLjI1tbm9wcXJzdHV2d5mam3t8fH1+f4CBgoOEp6akgYB+fXt6eHd1dHOSkZBta2ppZ2ZlY2JgX39+fFpYV1ZUU1JRT05NbW1vT1BRU11eX2FiY2SHiIlpa2xtbnBxcnR1dpmam5x8fn+AgYOEhYeIqqqpqIWEgoGAf318e3qamJeWc3Jxb25tbGppaIiHhYRiYF9eXFtaWVdWdnZ3eVlaW1xeX2BhY2SGiImKamxtbm9xcnN0dpiZm5x8fX+AgYKEhYaHqqqpqIWEg4KAf359e3p5mZeWdHJxcG9tbGtqaGeHhoRiYV9eXVxaWVhXVXZ3eFhZW1xdX2BhYmRlh4mKamtsbm9wcnN0dXeZmpx8fX5/gYKDhYaHiKupqIaEg4KBf359fHp5mZiWdHNxcG9ubGtqaWeHhoViYWBeXVxbWVhXVnZ3eHlZWlxdXl9hYmNlh4iKi2tsbW9wcXJ0dXaZmpudfX5/gIKDhIWHiKqqqaeFhIKBgH99fHt5mZiXlnNycW9ubWxqaWiIhoWEYWBfXlxbWlhXVnZ2d3lZWltdXl9gYmNkh4iJimtsbW5wcXJzdXZ3mpucfH5/gIGDhIWGiImqqaiFhIOBgH9+fHt6eZiXlnNycXBubWxraWhnh4WEYmBfXl1bWllYVlV2d3hYWltcXV9gYWNkZYiJimprbW5vcHJzdHZ3mZucfH1+gIGCg4WGh4mrqaiGhIOCgH9+fXt6eZmYlpVzcXBvbWxramhnh4aFg2FgXl1cWllYV1V1d3h5WVtcXV5gYWJjZYeIiotrbG5vcHFzdHV2mZqbnX1+f4GCg4SGh4irqqinhYOCgYB+fXx7eZmYl5VzcnBvbm1ramloh4aFhGFgX11cW1pYV1ZVdnh5WVpbXV5fYWJjZGaIiYtrbG1ucHFydHV2d5qbnHx+f4CBg4SFh4iJqqmnhYSCgYB/fXx7eniYl5ZzcnFvbm1samloZ4eFhGJgX15cW1pZV1ZVdnd5WVpbXF5fYGFjZGWIiYpqbG1ub3Fyc3R2d5mbnJ19f4CBgoSFhoeJqqmop4SDgoB/fnx7enmZl5aVcnFwb21sa2loZ4eGhINhX15dXFpZWFZVdnd4eVpbXF1fYGFiZGWHiYqLa21ub3Byc3R1d5manJ19foCBgoOFhoeIq6mop4SDgoF/fn18enl4mJaVc3Fwb25sa2ppZ2aGhYNhYF5dXFtZWFdWVHd4eVlaXF1eX2FiY2VmiIqLa2xtb3BxcnR1dniam519fn+AgoOEhYeIiaqpp4WEgoGAfn18e3l4mJeWc3Jxb25ta2ppaGaGhYRhYF9eXFtaWFdWVXZ3eXpaW11eX2BiY2RliImKjGxtbnBxcnN1dneam5ydfn+AgYOEhYaIiaqpqKaEg4GAf358e3p4mJeWlXJxcG5tbGtpaGeHhYSDYF9eXVtaWVhWVXZ3eHpaW1xeX2BhY2RliImKi2xtbnBxcnN1dnd5mpucfn+BgoOFhoeJiouop6WGhYOCgYB/fXx7epWUk3V0cnFwb21sa2ppg4KAZGNhYF9eXFtaWVhzdHZdXmBhYmRlZmhpaoSFh29xcnN1dnd5ent9lZeYgoOFhoeJiouMjo+ko6GKiYiHhoSDgoF/fpKQj454d3Z1c3JxcG5tf358e2dmZWNiYWBfXVxvcHFyYmRlZmhpamttboCBgoN1dnd5ent9fn+BkZKTlIeIiouMjo+QkpOgn52cjo2LiomIh4WEg46Mi4p9fHp5eHd1dHNye3p5d2xraWhnZmRjYmFha2xuZmdpamttbm9xcnN8fX95ent9fn+AgoOEho2PkIuMjo+QkpOUlpeXm5qYkpGQj46Mi4qJh4aIh4aBgH9+fXt6eXh2dXZ1c3Bvbm1ramloZ2VlZ2hpamttbm9wcnN0dnd4eXt8fX6AgYKDhYaHiYqLjI6PkJGTlJWWmJmamZiWlZSSkZCPjYyLioiHhoWDgoF/fn18enl4d3V0c3Jwb25sa2ppZ2ZlZmdpamtsbm9wcXN0dXZ4eXp8fX5/gYKDhIaHiImLjI2PkJGSlJWWl5mamZiXlZSTkpCPjo2LiomHhoWEgoGAf318e3p4d3Z0c3Jxb25tbGppaGdlZmdoaWtsbW9wcXJ0dXZ3eXp7fH5/gIKDhIWHiImKjI2Oj5GSk5WWl5iampiXlpSTkpGPjo2MiomIh4WEg4GAf358e3p5d3Z1dHJxcG5tbGtpaGdmZWdoaWpsbW5vcXJzdHZ3eHp7fH1/gIGChIWGh4mKi42Oj5CSk5SVl5iZmpmXlpWUkpGQj42Mi4mIh4aEg4KBf359fHp5eHZ1dHNxcG9ubGtqaGdmZWZnaWprbW5vcHJzdHV3eHl6fH1+gIGCg4WGh4iKi4yNj5CRk5SVlpiZmpmYlpWUk5GQj46Mi4qJh4aFg4KBgH59fHt5eHd2dHNycG9ubWtqaWhmZWZoam1vZ2doaGhoaWlpaWpqjI+Rk2tsbGxsbW1tbW5ubm6ys7W2dXZ4eXl3dnV0cnFwb66trKppZ2ZlZGJhYF9eXFuZmJeWlFRTUVBPTkxLSklIRoSGh4hMTU5QUVJUVVZXWVpbmZucnWJjZWZnaWprbG5vcHKur7GyeHp7fH17enl4dnV0rKuqqW5ta2ppaGZlZGNiYF+WlZSSWVhXVVRTUlBPTk1MSoGCg4RPUFJTVFZXWFlbXF2UlZeYmWVnaGlqbG1ucHFydKmqq616e31+f4B/fn18enl4qainpXJxb25tbGppaGdmZGOTkpCPXVxbWVhXVlRTUlFQfn1+f4BSVFVWV1laW11eX2GQkZOUZ2hqa2xub3Byc3R2d6Wmp6l9f4CBg4SDgoGAfn18pqWjonZ1c3JxcG5tbGtqaJGQjo1iYWBfXVxbWlhXVlVUe3l6e1RVV1hZW1xdX2BhY2SMjY+QamxtbnBxcnR1dnh5oKGio6WBgoOFhoeHhoWEgoGko6Gge3p5d3Z1dHJxcG9ubI6Mi4pmZWRjYWBfXlxbWllYd3Z2d1dYWltcXl9gYWNkZYiJiotrbW5vcXJzdHZ3eHl7nZ6goYGChIWGh4mJiIeFhIOjoqCffXt6eXh2dXRycXBvj42Mi4pnZmVjYmFfXl1cWll5eHd2VldYWVtcXV5gYWJkZYeJiotrbG5vcHFzdHV3eHl6nZ6foYGCg4SGh4iKiIeGhaWjoqGffXx6eXh3dXRzcnBvj46Mi2lnZmVkYmFgX11cW1l5eHd2VVdYWVpcXV5fYWJjZIeIiYtrbG1vcHFydHV2d3mbnJ6ff4CCg4SFh4iJiYeGhaWkoqF/fXx7enh3dnRzcnFvj46NjGloZ2VkY2FgX15cW3t6eXd2VVZXWVpbXF5fYGJjhYeIiWlqbG1ub3Fyc3V2d3ibnJ2ff4CBgoSFhoiJiYiHhaWko6F/fnx7enl3dnV0cnGRkI6NjGloZ2ZkY2JhX15dW3t6eXhVVVZXWFpbXF1fYGFihYaHiWlqa21ub3Byc3R1d3ianJ2efoCBgoOFhoeIiYiHp6ako4F/fn17enl4dnV0c3GRkI+Oa2poZ2ZlY2JhYF5dXHx7eXhVVFVXWFlbXF1eYGGDhYaHiGhqa2xub3Bxc3R1dpmam519fn+BgoOEhoeIiYmHp6alo4GAfn18e3l4d3Z0c3KSkI+Oa2ppaGZlZGNhYF9dfXx7eldWVVVWWFlaW11eX2CDhIWHZ2hpa2xtbnBxcnN1dpmam5x8fn+AgYOEhYaIiYmpqKalpIGAf318e3p4d3Z1c5OSkY9tbGppaGdlZGNiYF9efnx7eldWVVVWV1laW1xeX2CDhIWGZmhpamxtbm9xcnN0l5iZm5x8fX+AgYKEhYaHiYmpqKelg4KAf359e3p5eHZ1dJSSkZBtbGtqaGdmZWNiYV9efn18elhXVVRWV1hZW1xdX4GChIVlZmdpamtsbm9wcnN0l5iZmnp8fX5/gYKDhYaHiIqqqKemg4KBf359fHp5eHd1lZSTkZBubGtqaWdmZWRiYWCAfn18WVhXVlRVV1hZWlxdXoGCg4RkZmdoamtsbW9wcXJ0lpeZmnp7fX5/gIKDhIWHiKqqqaeFhIKBgH99fHt5eHd2lpSTkm9ubWxqaWhmZWRjYWCAf358WllXVlVVVldZWltdf4CCg4RkZWdoaWpsbW5wcXKVlpeYeHp7fH1/gIGDhIWGiKqqqaiFhIOBgH9+fHt6eXd2lpWTknBubWxraWhnZmRjYoKAf359WllYVlVVVldYWltcf4CBgmJkZWZoaWprbW5vcHKUlZeYeHl7fH1+gIGCg4WGh6qrqaiGhIOCgX9+fXt6eXiYlpWUcXBvbmxramhnZmVjYoKBgH5cW1lYV1VUVVdYWVtcfoCBgmJjZWZnaGprbG5vcJOUlZaYeHl6e31+f4GCg4SGqKmrqoeGhYOCgYB+fXx7eXiYl5WUcnBvbm1ramloZmVkYoKBgH9cW1pYV1ZVVVZYWVp9fn+AgmJjZGZnaGlrbG1ucJKTlZZ2d3l6e3x+f4CBg4SFqKmqqoiGhYSDgYB/fXx7eniYl5aVcnFwbm1samloZ2VkhIOCgF5dW1pZV1ZVVVZXWVp8fn+AYGFjZGVmaGlqbG1ub5KTlJZ2d3h5e3x9f4CBgoSmp6mqqoiHhYSDgoB/fn17epqZl5Z0cnFwb21sa2poZ2ZkhIOCgV5dXFpZWFdVVFZXWFl8fX6AYGFiZGVmZ2lqa2xukJGTlHR1d3h5enx9fn+BgoOmp6iqioiHhoWDgoF/fn18epqZmJd0c3Jwb25sa2ppZ2aGhYSCgV5dXFtZWFdWVFVXWHp8fX5eX2FiY2VmZ2hqa2xtkJGSlHR1dnh5ent9fn+AgoOlp6ipiYmHhoWEgoGAf318nJuZmJd0c3Jxb25tbGppaGaGhYSDYF9eXFtaWVdWVVVWV3p7fH5eX2BiY2RlZ2hpamxtj5GSk3N1dnd4ent8fX+AgaSlpqiIiYmIhoWEg4GAf358nJuamHZ1c3JxcG5tbGtpaGeHhYSDYF9eXVtaWVhWVVVWeHp7fH1dX2BhY2RlZmhpamuOj5CScnN0dnd4eXt8fX6AgaOlpqeHiYmIh4aEg4KBf359nZuamXZ1dHNxcG9ubGtqaIiHhoWDYWBeXVxbWlhXVlVWd3l6e11eX2FiY2VmZ2hqa2yMjY6Qc3R2d3h6e3x+f4CCoKGio6SJi4yLiomHhoWEg4GbmpmXe3p5eHZ1dHNycG9ubYWDgoFnZWRjYmFfXl1cWllac3R1dmFiY2RmZ2hqa2xub4aHiYqLd3h6e3x9f4CBg4SFm5ydn4yNj5CQj42Mi4qIh4aXlpWTgH99fHt6eXd2dXRzcYGAfn1ramloZmVkY2JgX15tbm9xY2RmZ2hqa2xub3Byc4KDhIV5e3x9f4CBg4SFh4iJlpiZmpCRk5SUk5KRj46NjJWTkpGPhYOCgYB+fXx7enh3fn18enFwb21sa2ppZ2ZlZGJoamtsZ2hqa2xub3Byc3R1d31+f4F9f4CBg4SFh4iJi4yQkpOUlZSVlpiZmJeVlJOSkJGQjo2KiYiHhYSDgoF/fn18enl4d3V0c3Jwb25ta2ppZ2ZlZmdoamtsbm9wcXN0dXZ4eXp7fX5/gYKDhIaHiImLjI2OkJGSlJWWl5mamZiXlZSTkpCPjo2LiomIhoWEgoGAf318e3p4d3Z1c3Jxb25tbGppaGdlZmdoaWtsbW5wcXJ0dXZ3eXp7fH5/gIGDhIWHiImKjI2Oj5GSk5SWl5iampiXlpWTkpGPjo2MiomIh4WEg4KAf358e3p5d3Z1dHJxcG9tbGtpaGdmZWZoaWpsbW5vcXJzdHZ3eHl7fH1/gIGChIWGh4mKi4yOj5CSk5SVl5iZmpmXlpWUkpGQj42Mi4mIh4aEg4KBf359fHp5eHZ1dHNxcG9ubGtqaWdmZWZnaWprbG5vcHJzdHV3eHl6fH1+f4GCg4WGh4iKi4yNj5CRkpSVlpiZmpmYl5WUk5GQj46Mi4qJh4aFhIKBgH59fHt5eHd2dHNycW9ubWtqaWhmZWZnaGprbG1vcHFydHV2eHl6e31+f4CCg4SFh4iJi4yNjpCRkpOVlpeYmpmYl5aUk5KRj46Ni4qJiIaFcIaRhXyTfmZvZ2dcfIlpiX58YFlKZnyHjomcak5LN1FJOU82V1ZkRmRZWHuinY+haWNJUGJeblpnd3lpf4GDhcezpq67kHJrhWmNlWRvfGVeZIB3abeUl5ekcm5FcWJOPVteRlpKPERPSnlva4FsQlJAME8+RVJPUERGVl1WXIqkraCtX2CBYYqBjIp0aoqBaINwdsajzczEho2BZHp7ZHZvX1hgcFBrUYmXpZyNXmFbVU1fRGNMYEpHZkhcSn+AmnqGWGhWS2ZraGZsXVxsXVl3do6LkayIXFluYWJYcVdue2pofINufZOes7KstGZscXyBcWqEhmpvhoVrdK+bmaWUjXl7YGpud2BiaVNnTk9HVHeGdnqGc1JaXF9PU1ZYUF1OY0xMWomRnIOAmGVsanhwg2V2g3Z4i4V+joC4tLa0qoB6ipKMfn92c3Z+aWplc3iYooiLgG9vbltTT2FfU1VOWVRETEh+amlwaUxMVFNaZmRVZlxia2xoZ3GSi6KTqHduhXF4dIFycntyfod9f4izmZ2gooN/eHVwh22Bd4JydGxyZW6Pm4yKhXJmbV9mY3Fcb19kZlxrXmiKgHp7iFRnWF9iWF1nb2dhY25lanGNhoWElnVsa2Vvbnd6eHh8doV8eI2Yna+qpIR8goR8f4SIhX56eYN8g2+Wl5Ocl3N3andjYHBhaGRjZGJjWVJtb3B3cHBUVExWWVxTXFdnZGRraGmDloiSh519cnp/eX2Id4aEgYSQio6qpLG1tqWHhIl8foiAd4J/f3ZycW6JiouGjoZfXW1qaF9pXmFlVlxdVVFUcHZ/fHVSWmRlaFtoZWxeamFpa3NxjoyamJpyen1xfHp8fHl0fYJ+fnl6n6mlrKiFiH97hIJ6gIF8e3h0c3t2jZmYlYp2bG9tbGJubmxrZGZjWF9eeYByen1aXGFZWV9eXGRkW2VlXmlggoiGjodycXBwc3lveXx6fXiEe3yKo6ikraeQjoOIgIWAgH58fnx+e3JzmJaWkJNzbWlibWVjXFllXVtfX11TenJ0dXROW1JZV1VbWWRfY2ljaGhljZWNl5B0fHR5d3h5e36Dgn2Din+KqK2wraqliImFfYR9d312dHVxdXJskouQjo6IaWJjZWFeaGhmX2FcYmBdeH15fHV6XGBaYl1gYWNhZGpjY2dtjIuPjI2ObXh0b3pxdXl0dn14fIF/h6OiqqSrg4J+g4OAhHuAeIB8fXh5dpSUj5aRcWhqaGdsaGRlZ2BiWmFcXn18dHVzVFhUWVxcXVtkXGRjYWFpZ4qHkYyScnFydHR7fH+Ag4CGgoeCi6upqquph4WEg4KAf359e3p5eHZ1dJSSkZCPbGtqaGdmZWNiYWBeXVxbWXl4d3Z3V1haW1xdX2BhYmRlZmdpaoyOj5CRcXN0dXZ4eXp7fX5/gIKDhKaoqaqph4WEg4KAf359e3p5eHZ1dJSTkZCPbWtqaWhmZWRjYmBfXl1bWnp5eHd3V1laW1xdX2BhYmRlZmdoaoyNj5CRknJzdXZ3eHp7fH1+gIGCg6anqKmpqIWEg4KAf359e3p5eHd1dJSTkpGPjmxraWhnZmVjYmFgX11cW1p6eXd4eVlaW1xeX2BhYmNlZmdoaWuNjo+RknJzdHV3eHl6e3x+f4CBgoSmp6ipp4WEg4GAf359fHp5eHd2dHOTkpGQj2xramlnZmVkY2JgX15dXFt7enh4eVlaW1xeX2BhYmNlZmdoaWqNjo+QkXFzdHV2d3h6e3x9fn+AgoOlpqeop4WEgoGAf359fHp5eHd2dXOUkpGQj21ramloZ2ZlY2JhYF9eXVt8enl4eVlaW11eX2BhYmNlZmdoaWqNjo+QkXFyc3R2d3h5ent8fX+AgYKkpaeop4WDgoGAf359fHp5eHd2dXSUk5KQj45sa2poZ2ZlZGNiYWBeXVx8e3p5eXtaXF1eX2BhYmNkZmdoaWqMjY+QkZJyc3R1dnd4eXt8fX5/gIGkpaanp6aDgoGAf359fHp5eHd2dXRzk5KRkI9sa2ppaGdmZWNiYWBfXl1cfHt6entbXF1eX2BhYmNkZWdoaWprjY6PkJJxcnR1dnd4eXp7fH1+f4CBpKWmpqWDgoGAf359fHp5eHd2dXRzk5KRkI9tbGppaGdmZWRjYmFgX15dfXx7entbXF1eX2BhYmNkZWZoaWprjY6PkJFxcnN0dXZ3eHl6fH1+f4CBo6SlpqWDgoGAf359fHp5eHd2dXRzk5KRkI9tbGtqaWhnZmVkY2JhX15dfn18e3tbXF1eX2BhYmNkZWZnaGprjY6PkJGScnN0dXZ3eHl6e3x9fn+AoqOkpaWkgoGAf318e3p5eHd2dXRzlJOSkI+ObGtqaWhnZmVkY2JhYF9efn18e3x9XF1eX2BhYmNkZWZnaGlqa46PkJGScXJzdHV2d3h5ent8fX5/gKKjpKWkgYB/fn18e3p5eHd2dXRzcpOSkZCPbWxramloZ2ZlZGNiYWBfXn59fHx9XV5fX2BhYmNkZWZnaGlqa42Oj5CRcXJzdHV2d3h5ent8fX5+f6KjpKSjgYB/fn18e3p5eHd3dnV0c5OSkZCPbWxramloZ2ZlZGNiYmFgX39+fXx9XV5fYGFiY2NkZWZnaGlqa42Oj5CRcXJzdHR1dnd4eXp7fH1+f6Gio6SjgYB/fn18e3p6eXh3dnV0c5OSkZCPjm1sa2tqaWhnZmVkZGNiYX59fHt8fGBhYmNkZWZnaGlqa2xtboqLjI2Oj3R1dnd4eXp7fH1+f4CBgpydnp+fnoSDgoGAf39+fXx7enl5eHeOjYyLinJxcG9ubm1sa2ppaGhnZmV6eXh4eGRlZmdoaWprbG1ub3BxcnOHiIiJinh5ent8fX5/gIGCgoOEhYaYmZqamYiHhoWEhIOCgYB/f359fHuJiYiHhnZ1dXRzcnFxcG9ubW1sa2p2dXR0dWlqa2xtbm5vcHFyc3R1dneCg4SFhnx9fn+AgYKCg4SFhoeIiYqTlJWWlYyLiomIiIeGhYSEg4KBgICFhISDgnt6eXh4d3Z1dXRzcnFxcG9zcnFwcW1ub3BxcnN0dXV2d3h5ent+f4CAgYCBgoOEhIWGh4iJiouLjI2Oj5CRkI+Pjo2Mi4qKiYiHhoaFhIOCgYGAf359fXx7enl4eHd2dXR0c3JxcHBvb3BxcXJzdHV1dnd4eXl6e3x9fX5/gIGCgoOEhYaGh4iJiYqLjI2Njo+QkI+Ojo2Mi4qKiYiHhoaFhIOCgoGAf35+fXx7enp5eHd3dnV0c3NycXBwb3BxcnJzdHV2dnd4eXl6e3x9fX5/gICBgoOEhIWGh4eIiYqKi4yNjo6PkI+OjYyMi4qJiYiHhoaFhIOCgoGAf39+fXx8e3p5eXh3dnZ1dHNzcnFwcHBxcnNzdHV2dnd4eXl6e3x8fX5/f4CBgoKDhIWFhoeIiImKi4uMjY6Oj46OjYyLi4qJiYiHhoaFhIODgoGAgH9+fX18e3t6eXh4d3Z1dXRzc3JxcHFxcnN0dHV2d3d4eXl6e3x8fX5/f4CBgYKDhISFhoaHiImJiouLjI2Ojo6NjYyLi4qJiIiHhoaFhIODgoGBgH9+fn18fHt6enl4d3d2dXV0c3NycXFycnN0dXV2d3d4eXp6e3x8fX5+f4CAgYKDg4SFhYaHh4iJioyOj4eHhoaEgoF/fXx6eJmZmZpwbmxraWdmZGJgX11bnZycm1hYV1ZWVVVUU1NSUVGTk5SUVVVWV1dYWVpaW1xcnZ2en59hYWJjZGRlZmZnaGinqKipbG1tbm9ubW1sbGtqaqalpKRnZmVlZGRjYmJhYWBfmpmYmFxcW1taWVlYWFdWVo+PkJFYWFlaW1tcXV1eX19gmZqam2NkZWVmZ2doaWpqa2yjpKSlb3BwcXJxcXBwb25uo6KhoaBqamloaGdnZmZlZGSXl5aVYWBgX19eXl1cXFtbWoyMjY1cXF1eXl9gYGFiYmNklZaWl2doaGlpamtrbG1tbp6fn6ChcnNzdHR1dHNzcnJxn56dnW5ubW1sbGtqamlpaGiUk5OSZWRkY2NiYmFhYGBfXomJiYpgYGFiYmNjZGVlZmeRkpKTamprbGxtbW5vb3BxcZqbm5x0dXV2d3d4d3d2dnV1m5qamXJxcXBwb29ubm1tbJGQkI+PaWhoZ2dmZmVlZGRjh4aGhmNkZGVlZmdnaGhpamqNjo6PbW5ub3BwcXFyc3N0dJaXl5h3eHh5eXp6enl5eHiYmJeXdXR0c3NycnFxcHBvbo+Pjo5sa2tqamlpaGdnZmZlhoaFhWVlZmZnZ2hoaWlqaoyNjY6Obm5vb3BwcXFycnNzlZaWl3Z3d3h4eXl6enl4eHeYmJeXdXR0c3NycnFxcHBvb4+Pjo5sbGtramppaWhoZ2eHh4aGhmVmZmdnaGhpaWpqa4yNjY5tbm5vb3BwcXFycnNzlZWWlnZ2dnd3eHh5eXl4eHeYl5eWdXR0c3NycnFxcHBvkJCPj21sbGtramppaWloaGeIh4eGZWVmZmdnaGhpaWpqa4yNjY5tbm5ub29wcHFxcnKUlJWVlnV1dnZ3d3h4eXh4d5iYl5d1dHR0c3NycnFxcHBvkJCPj21tbGxra2pqaWlpaGiIiIiHZWZmZ2doaGlpaWpqjIyNjY5tbW5ub29wcHFxcXKUlJSVdHV1dXZ2d3d4eHh3d5iXl5Z1dHRzc3JycnFxcHBvkJCPj21tbGxsa2tqamppaYmJiYhnZmZnZ2hoaGlpamprjI2NjW1tbW5ub29wcHBxcXKTlJSUdHR0dXV2dnZ3d3d3mJeXlpZ0dHRzc3JycnFxcHCRkJCQbm5tbWxsbGtrampqaYqKiYlnZ2dnaGhoaWlqamprjI2NjW1tbW5ub29vcHBxcZOTk5Rzc3R0dHV1dXZ2d3d2l5eXlnV0dHNzc3JycXFxcHCRkJCQbm5tbW1sbGxra2pqi4uKioloaGdoaGhpaWlqamuMjI2NbG1tbW5ub29vcHBwcZKTk5Nyc3N0dHR1dXV2dnZ2l5eWlnR0dHNzcnJycXFxcJGRkZCQbm5ubW1tbGxsa2tri4uLimloaGhoaGlpaWpqamuMjY2NbG1tbW5ubm9vb3BwcJKSk5NycnNzc3R0dHV1dXaXlpaWdHR0c3NzcnJycXFxcJGRkZBvbm5ubW1tbWxsbGtrjIyLi2lpaWhoaWlpampqa4yNjY2NbW1tbW5ubm9vb3BwkZKSknFycnJzc3N0dHR0dXWWlpaVdHRzc3NycnJxcXFxcJGRkZBvb25ubm1tbW1sbGyNjIyMampqaWlpaWpqampra4yNjY1sbW1tbm5ubm9vb29wkZKSknFxcnJycnNzc3R0dJaWlpWVc3Nzc3JycnJxcXFwkZGRkW9vb25ubm5tbW1tbGyNjYyMa2tqampqampqa2tra42NjY5tbW1tbm5ubm9vb2+RkZGSknFxcXJycnJzc3Nzc5WVlZVzc3NzcnJycnFxcXFwkZGRkW9vb25ubm5ubW1tbWyNjY2Na2tra2pqampra2trjY2Njm1tbW1tbm5ubm9vb2+RkZGRcHFxcXFxcnJycnJzc5SVlZRzc3JycnJycXFxcXCRkZGRkW9vb29ubm5ubm1tbY6Ojo1sbGxra2tra2tra2xsjY2Ojm1tbW1ubm5ubm9vb2+RkZGRcHBwcXFxcXFycnJylJSUlJRycnJycnFxcXFxcXCRkZGRb29vb29vbm5ubm5tbY6Ojo5sbGxsbGxra2tsbGxsjo6Ojm1tbW5ubm5ubm9vb5CQkZFwcHBwcHFxcXFxcXFyk5OTk3JycnJxcXFxcXFwcHCRkZGRb29vb29vbm5ubm5uj4+Ojo5tbW1sbGxsbGxsbGyOjo6ObW1tbm5ubm5ubm9vb5CQkJFwcHBwcHBwcHFxcXFxkpOTk3JxcXFxcXFxcHBwcJGRkZFvb29vb29vb25ubm5uj4+Pj21tbW1tbW1tbGxtbW2Ojo6PbW5ubm5ubm5ubm9vkJCQkJBvb3BwcHBwcHBwcHGSkpKScXFxcXFxcHBwcHBwcJGRkZFvb29vb29vb29ubm5uj4+Pj25ubm1tbW1tbW1tbY+Pj4+Pbm5ubm5ubm5ub29vkJCQkG9vb29vcHBwcHBwcHCRkZKScHBwcHBwcHBwcHBwcJGRkZFvb29vb29vb29vb26QkJCPbm5ubm5ubm5ubm5ubo+Pj49ubm5ubm5ubm9vb29vkJCQkG9vb29vb29vb3BwcJGRkZGRcHBwcHBwcHBwcG9vkZGQkG9vb29vb29vb29vb2+QkJCQbm5ubm5ubm5ubm5ubo+QkJBubm5vb29vb29vb2+QkJCQkG9vb29vb29vcHBwcJCQkJBwcHBwcHBwcHBwcHBxj4+Pj3FxcXFxcXFxcXFxcY6Ojo6OcXFxcXFycnJycnJyjY2NjXJycnJycnJzc3Nzc3OMjIyMc3Nzc3Nzc3NzdHR0dIuLi4t0dHR0dHR0dHR0dHSKioqKinV1dXV1dXV1dXV1dYqKiYl2dnZ2dnZ2dnZ2dnZ2iYmJiXZ3d3d3d3d3d3d3d3eIiIiId3d3d3h4eHh4eHh4h4eHh3h4eHh4eHh4eXl5eXmGhoaGeXl5eXl5eXl5eXl6eoWFhYV6enp6enp6enp6enqFhISEhHt7e3t7e3t7e3t7e4SEhIR8fHx8fHx8fHx8fHx8g4ODg3x8fH19fX19fX19fX2CgoKCfX19fX19fn5+fn5+gYGBgYF+fn5+fn5+fn5/f3+AgICAf39/f39/f39/f39/gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICFjJOZn6arsaapq62vsLCxsLCurauopaGemZWQir+8uLOvqqRcV1FMR0E8NzMuKiYjIB0aGBYVFBNUVVdZXF9iJSktMjY7QEVKUFVaYGVqb3R5foKGyMzP0tXY2p6goaKjo6Ojo6Khn56cmpiWlJKPjMS+ubSuqaRkYFtXU09MSEVDQD48Ojk4ODc3NzhxcnN1dnh6Q0VHSkxPUVNWWFtdX2FjZGZnaGlqoqSmqaqsrXh5enp6enp5eXh3dXRzcW9tbGpoZpiWlJKQj41YVlVUU1NSUlJSUlNUVVZYWVtdYGJll5eYmZqbnGxub3FydHZ3eXt8fn+BgoOEhYaHh7e3t7e2trWFhIOBf358eXd1cm9saWZjYFxZVVJ9e3p5d3Z1R0ZFRENCQkFBQUBAQEFBQkJDREVHc3R2eHp8fldZXF9iZWhrbnJ1eHx/goaJjZCTl8HBwsPDw8ScnZ2cnJycm5qZmJeWlZOSkI6MioirqaakoZ6bc3Fua2hlYl9cWVZTUE1KR0VCPz06XFxcXFxcXTs7PD0+P0BCQ0VGSEpMTlBSVVdZXH+ChYeKjY9xdHZ5fH+BhIeKjI+RlJaZm52foaOlxsbFxMTDwqCfnZybmZiWlZORj42LiYeFgoB+e5qYlZOQjotoZWNgXltZV1RSUE1LSUdFQ0E/PTtdXV5fX2BhQUJDREZHSUpMTU9RUlRWWFpcXmBihYiKjI6Qk3R2eHt9f4GDhoiKjI6QkpSWmJqcnr+/vr69vLuZmZiXlpWTkpGQjo2LioiHhYSCgH6enJqYlpSTb21raWdlY2FfXVtZV1VTUU9NTEpIaGhpaWlqakpKS0xMTU5PUFBRUlNUVldYWVpcXX+BgoSFh4hpamxtb3FzdHZ4eXt9f4GChIaIiouurq6tra2srIqKiomJiIiHh4aFhYSEg4KBgYB/fp6dnZybmph2dXRzcnBvbm1ramlnZmRjYWBfXVx9fX5+f3+AX2BgYWFhYmJjY2RkZWVmZmdnaGhpiouLjI2Njm1ub29wcXFyc3R1dXZ3eHl6e3x9fp+enZybmpl3dnV1dHNycXFwb25ubWxsa2pqaWmJiYiHh4aGZGNjYmFhYGBfX15eXVxcW1taWVlYeXt8fX+AgWFjZGVnaGlqa21ub3BxcnR1dnd4eZucnZ6foKGBgoOEhYaHh4iJiouMjI2Oj5CQkZKTs7Gwr66sq4mHhoWEgoGAf318e3l4d3Z0c3Jwb4+OjYuKiYhlZGNhYF9eXVtaWVhXVVRTUlFQT01vcHFxcnN0U1RVVldYWVpaW1xdXl9gYWJjZGVmiImKi4yNjnZ3eHl6e3x9fn+AgYKCg4SFhoeIiaqpqKenpqWCgoGAf359fHt6eXh3dnV0c3JxcG+Qj46NjIuKaGdmZWRjYmFgX15dXVxbWllYV1ZVdnd4eXl6e1tcXV5fYGFiY2RlZmZnaGlqa2xtbpCRkpOUlZZ2d3h5eXp7fH1+f4CBgoOEhYaHiImrqqmop6alpIKBgH9+fXx7enl5eHd2dXRzcnFwb4+OjYyLi4pnZmZlZGNiYWBfXl1cW1pZWFdWVVR2d3h5ent8XF1dXl9gYWJjZGVmZ2hpamtsbW5vkZKTlJSVlnZ3eHl6e3x9fn+AgYKCg4SFhoeIiaqpqKenpqWCgoGAf359fHt6eXh3dnV0c3JxcG+Qj46NjIuKaGdmZWRjYmFgX15dXVxbWllYV1ZVdnd4eXl6e1tcXV5fYGFiY2RlZmZnaGlqa2xtbpCRkpOUlZZ2d3h5eXp7fH1+f4CBgoOEhYaHiImrqqmop6alpIKBgH9+fXx7enl5eHd2dXRzcnFwb4+OjYyLi4pnZmZlZGNiYWBfXl1cW1pZWFdWVVR2d3h5ent8XF1dXl9gYWJjZGVmZ2hpamtsbW5vkZKTlJSVlnZ3eHl6e3x9fn+AgYKCg4SFhoeIiaqpqKenpqWCgoGAf359fHt6eXh3dnV0c3JxcG+Qj46NjIuKaGdmZWRjYmFgX15dXVxbWllYV1ZVdnd4eXl6e1tcXV5fYGFiY2RlZmZnaGlqa2xtbpCRkpOUlZZ2d3h5eXp7fH1+f4CBgoOEhYaHiImrqqmop6alpIKBgH9+fXx7enl5eHd2dXRzcnFwb4+OjYyLi4pnZmZlZGNiYWBfXl1cW1pZWFdWVVR2d3h5ent8XF1dXl9gYWJjZGVmZ2hpamtsbW5vkZKTlJSVlnZ3eHl6e3x9fn+AgYKCg4SFhoeIiaqpqKenpqWCgoGAf359fHt6eXh3dnV0c3JxcG+Qj46NjIuKaGdmZWRjYmFgX15dXVxbWllYV1ZVdnd4eXl6e1tcXV5fYGFiY2RlZmZnaGlqa2xtbpCRkpOUlZZ2d3h5eXp7fH1+f4CBgoOEhYaHiImKqqmop6alpIKBgH9+fXx7enl5eHd2dXRzcnFwb4+OjYyLi4pnZmZlZGNiYWBfXl1cW1pZWFdWVVR2d3h5ent8XF1dXl9gYWJjZGVmZ2hpamtsbW5vkZKTlJSVlnZ3eHl6e3x9fn+AgYKCg4SFhoeIiaqpqKenpqWCgoGAf359fHt6eXh3dnV0c3JxcG+Qj46NjIuKaGdmZWRjYmFgX15dXVxbWllYV1ZVdnd4eXl6e1tcXV5fYGFiY2RlZmZnaGlqa2xtbpCRkpOUlZZ2d3h5eXp7fH1+f4CBgoOEhYaHiImqqainpqWko4OCgYB/f359fHt6eXh3dnZ1dHNycY2Mi4qJiIdqaWhnZmVlZGNiYWBfXl1cXFtaWVhzc3R1dnd4X2BhYmNkZWZnaGlqa2xtbm9wcXJzjI2Ojo+QkXt8fX5/gIGCg4SFhoeIiYqLjI2Oj6SjoqGgn56JiIeGhoWEg4KBgH9+fX18e3p5eHeIh4aFhIOCcG9ubWxsa2ppaGdmZWRjY2JhYF9ebG1ub3BxcmVmZ2hpamtsbW5vcHFyc3R1dnd4eYaHh4iJiouBgoOEhYaHiImKi4yNjo+QkZKTlJWfnp2cm5qZmI6OjYyLiomIh4aFhYSDgoGAf359fIKBgH9+fXx1dHNzcnFwb25tbGtqamloZ2ZlZGNnaGlqa2xta2xtbm9wcXJzdHV2d3h5ent8fX5/gIGCg4SFhoeIiYqLi4yNjo+QkZKTlJWWl5iZmpqZmJeWlZSTkpGQj46NjIuLiomIh4aFhIOCgYB/fn18e3p5eXh3dnV0c3JxcG9ubWxramloZ2ZmZWZnaGlqa2xtbm9vcHFyc3R1dnd4eXp7fH1+f4CBgoKDhIWGh4iJiouMjY6PkJGSk5SUlZaXmJmamZiXlpWUlJOSkZCPjo2Mi4qJiIeGhYSDgoKBgH9+fXx7enl4d3Z1dHNycXBvb25tbGtqaWhnZmVmZmdoaWprbG1ub3BxcnN0dXZ3eHl5ent8fX5/gIGCg4SFhoeIiYqLi4yNjo+QkZKTlJWWl5iZmpqZmJeWlZSTkpGQj46NjIuLiomIh4aFhIOCgYB/fn18e3p5eXh3dnV0c3JxcG9ubWxramloZ2ZmZWZnaGlqa2xtbm9vcHFyc3R1dnd4eXp7fH1+f4CBgoKDhIWGh4iJiouMjY6PkJGSk5SUlZaXmJmamZiXlpWUlJOSkZCPjo2Mi4qJiIeGhYSDgoKBgH9+fXx7enl4d3Z1dHNycXBvb25tbGtqaWhnZmVnaGpsbmRkZGRkZGRkZGRkZGRjY2NjkpSVl5ljY2NjY2NkZWZnaGlqa2xtbrCxsrO0tXV2d3h5eXp5eHd2dXRzcnGwr66trKtramloZ2dmZWRjYmFgX15dXZmYl5aVV1ZVVFNTUlFQT05NTEtKSkmDg4SFhoZMTU5PUFFSU1RVVldYWVpblpeYmZmaYmNkZWZnaGlqa2xtbm9wcXKrrKytrnh5ent8fX5/fn18e3p5eXh3rKuqqaincG9vbm1sa2ppaGdmZWVkY5aVlJOSkVxcW1pZWFdWVVRTUlJRUE9Of35+f4BQUVJTVFVWV1hZWltcXV1eX5GRkpOUlWZnaGlqa2xtbm9wcXJzdHWkpaanqKl8fX5/gIGCg4OCgYGAf359fKempaSjd3Z1dHNycXBvbm5tbGtqaWiRkI+OjYxiYWBfXl1cW1paWVhXVlVUfHt6eXp7VFVWV1hZWltcXV5fYGFiY2SLjI2Oj2prbG1ub3BxcnN0dXZ3eHl6n6ChoqOkgYKDhIWGh4iJiIeGhYSDgqSjoqGgn3x7enl4d3Z2dXRzcnFwb25tjYyLi4pnZmZlZGNiYWBfXl1cW1pZWHl4d3Z2d1dYWVpbXF1dXl9gYWJjZGWHiImKi4xsbW5vb3BxcnN0dXZ3eHl6e52en6ChgYKCg4SFhoeIiYmIh4aFhIOko6KhoJ99fHt6eXh3dnV0c3JxcG9vj46NjIuKaGdmZWRjYmFgX15dXVxbWll5eHd2dlVWV1hZWltcXV5fYGFiY2Rlh4iJiotqa2xtbm9wcXJzdHV2d3h5eZydnp6foICBgoOEhYaHiImKiYiHhoWEpKOioaB+fXx7enl5eHd2dXRzcnFwb4+OjYyLaWhnZmZlZGNiYWBfXl1cW1p6eXl4d3ZVVldYWVpbXF1dXl9gYWJjZIaHiImKamtsbW5vb3BxcnN0dXZ3eHmbnJ2en3+AgYKCg4SFhoeIiYmIh4aFpqWko6Khf359fHt6eXh3dnV0c3JxcJGQj46NjGppaGdmZWRjYmFgX15dXVxbe3p5eHdVVFVWV1hZWltcXV5fYGFiY4WGh4iJimlqa2xtbm9wcXJzdHV2d3iam5ydnp5+f4CBgoOEhYaHiImKiYiHhqalpKOigH9+fXx7enl5eHd2dXRzcnGRkI+OjYxqaWhnZmZlZGNiYWBfXl1cfHt6eXl4VVRVVldYWVpbXF1dXl9gYWKEhYaHiGhpamtsbW5vb3BxcnN0dXZ3mZqbnJ2efn+AgYKCg4SFhoeIiYmIh6enpqWko4GAf359fHt6eXh3dnV0c3JxkpGQj45sa2ppaGdmZWRjYmFgX15dXX18e3p5eFZVVFVWV1hZWltcXV5fYGGDhIWGh4hnaGlqa2xtbm9wcXJzdHV2d5mam5ydfH1+f4CBgoOEhYaHiImKiYiop6alpKOBgH9+fXx7enl5eHd2dXRzk5KRkI+ObGtqaWhnZmZlZGNiYWBfXl19fHt6eVdWVVRVVldYWVpbXF1dXl9ggoOEhYaHZ2hpamtsbW5vb3BxcnN0dZeYmZqbnHx9fn+AgYKCg4SFhoeIiYmIqKenpqWCgoGAf359fHt6eXh3dnV0c5STkpGQj21sa2ppaGdmZWRjYmFgX15/fn18e3pYV1ZVVFVWV1hZWltcXV5fYIKDhIWGZmZnaGlqa2xtbm9wcXJzdHWXmJmam5x7fH1+f4CBgoOEhYaHiImKqqmop6alg4KBgH9+fXx7enl5eHd2dXSUk5KRkG5tbGtqaWhnZmZlZGNiYWBff359fHtZWFdWVVRVVldYWVpbXF1dXoGCgoOEhWVmZ2hpamtsbW5vb3BxcnN0lpeYmZp6e3x9fn+AgYKCg4SFhoeIiaqpqKenhIOCgoGAf359fHt6eXh3dnWVlJSTkpFvbm1sa2ppaGdmZWRjYmFgX4B/fn18WllYV1ZVVFVWV1hZWltcXV6AgYKDhGRlZmZnaGlqa2xtbm9wcXJzlZaXmJmaeXp7fH1+f4CBgoOEhYaHiKqrqqmop4WEg4KBgH9+fXx7enl5eHd2lpWUk5Jwb25tbGtqaWhnZmZlZGNiYYGAf359fFpZWFdWVVRVVldYWVpbXF1/gIGCgoNjZGVmZ2hpamtsbW5vb3BxcpSVlpeYeHl6e3x9fn+AgYKCg4SFhoepqqqpqKeFhIOCgoGAf359fHt6eXh3l5aVlJSTcG9vbm1sa2ppaGdmZWRjYmGCgYB/flxbWllYV1ZVVFVWV1hZWltcfn+AgYKDY2RlZmZnaGlqa2xtbm9wcZOUlZaXmHh5eXp7fH1+f4CBgoOEhYaHqaqrqqmHhoWEg4KBgH9+fXx7enl5eJiXlpWUk3Fwb25tbGtqaWhnZmZlZGODgoGAf35cW1pZWFdWVVRVVldYWVpbXH5/gIGCYWJjZGVmZ2hpamtsbW5vb3CTlJSVlpd3eHl6e3x9fn+AgYKCg4SFp6ipqqqph4aFhIOCgoGAf359fHt6eXiYl5aVlHJxcG9vbm1sa2ppaGdmZWRjg4KCgYB/XVxbWllYV1ZVVFVWV1hZWnx9fn+AgWFiY2RlZmZnaGlqa2xtbm9wkpOUlZZ2d3h5eXp7fH1+f4CBgoOEhaeoqaqrqoiHhoWEg4KBgH9+fXx7enmamZiXlpVzcnFwb25tbGtqaWhnZmZlZISDgoGAXl1cW1paWVhXVlVWV1hZWlt7fH1+fmFiY2RlZmdoaWprbG1ub3Bxj4+QkZKTeHl6e3x9fn+AgYKDhIWGh4ijpKWmp42Mi4qJiIeGhYWEg4KBgH9+lpWUk5J5eHd2dXRzc3JxcG9ubWxraoB/fn18e2RjYmJhYF9eXVxbW1xdXl9gdXZ2d3hmZ2hpamtsbW5vcHFyc3R1doiJiouMfH1+f4CBgoOEhYaHiImKi4ycnZ6foKGTkpGQj46NjIyLiomIh4aFhJGQj46Nf359fHt7enl4d3Z1dHNycnF7enl4d2tqaWloZ2ZlZGNiYWBhYmNkbm9vcHFya2xtbm9wcXJzdHV2d3h5eoGCg4SFhoGCg4SFhoeIiYqLjI2Oj5CRlpeYmZqXmJiXlpWUlJOSkZCPjo2Mi4yLiomIh4WEg4KCgYB/fn18e3p5eXh3dnV0c3JxcG9ubWxramloZ2ZmZWZnaGlqa2xtbm9vcHFyc3R1dnd4eXp7fH1+f4CBgoKDhIWGh4iJiouMjY6PkJGSk5SUlZaXmJmamZiXlpWUlJOSkZCPjo2Mi4qJiIeGhYSDgoKBgH9+fXx7enl4d3Z1dHNycXBvb25tbGtqaWhnZmVmZmdoaWprbG1ub3BxcnN0dXZ3eHl5ent8fX5/gIGCg4SFhoeIiYqLi4yNjo+QkZKTlJWWl5iZmpqZmJeWlZSTkpGQj46NjIuLiomIh4aFhIOCgYB/fn18e3p5eXh3dnV0c3JxcG9ubWxramloZ2ZmZWZnaGlqa2xtbm9vcHFyc3R1dnd4eXp7fH1+f4CBgoKDhIWGh4iJiouMjY6PkJGSk5SUlZaXmJmamZiXlpWUlJOSkZCPjo2Mi4qJiIeGhYSDgoKBgH9+fXx7enl4d3Z1dHNycXBvb25tbGtqaWhnZmVmZmdoaWprbG1ub3BxcnN0dXZ3eHl5ent8fX5/gIGCg4SFhoeIiYqLi4yNjo+QkZKTlJWWl5iZhp6onZShln+JgYF3l6SEpZqZfZyPrZqlfHSDg2RfSWFXRFg9XFmnhqOVkS9UTTxMVEwvNEQ+SzVAj5B/lZdZWlxIO0NTaU1JZUtxe4yZp5NQV3ZvY3VVWl1seXhRf7Cej6+1YnhqX2l2c2hgXnZhcoKsmbajp3ZxcGJicHVrb2F4f3F8n529msF8hIBpXHpvVGxXW3BLc6igm6JeQVhaQ1VPPzdAUDFMM2t6i4R3Sk9MSEJXPV5KYExMbVGcjY+Sr1xobn1rYXqAfHl/cG9/op68up9obollbGh8b3Bmf2V7iKejtLlxfWBpe3hyel5kaXV6a2OusZWZgYFncHxpZ3NiXHd5X2mcpo+RmFRpUFFKV01cTFFbRlBWhIZ1eXxRSFVGWkNDUVNbZk1KYYSLiZeOdlhodWdpfHVufm99eXuknJ2Zg42JfoB6eX2IdXl2ho2wuqCkmYiIh3Vtanx6b3FqdXFhkIyciYhoX2ZjamZrdHFfbmJmbJCKh46IW29ecWJXbFZaVV9OS1Nsd4B2VV1kS05SVltaVVRRalOKg5CChl9oXWdpeGtsaXlweGx2l6eUqZyBhn6PhJCTi4iLmISXiK+wo6aukoiAf4l9gIV9dHFtfnyRjoaOaXBxbWtsZHFmX3JaXWxlgYJ6gWJaXWNnZF5aWWNdZVBXeniDgYBlW2lYV2lcZmNkaGlrY4B8gYONZGRpaWFqbXBnb2l5dnaem5yUpneAdYuMgIiNh4qUg5KQrK23r4+IgImMjHx/fYF1d4F6kp6bm5JubWplZmdia2NeXGxqaIGKgIOIWF5fV1VXUlliXlVRV16Ag3aCfmRWYVhgYWlnY2BubG5mj5KGkGxubmplbnNubmlpbHZym5man5h1gIB7g4aDhIOCg46Lg7GwrqOxhYmHhn2KioiHgYOAdXydl5+RmXl0dHdta29rZ2xqX2dlfYZ6eX1XXlNeW1dVVllOVlZSU3B7cXJfVltXYFxoaV9nYWhmZ4mJjo6Rb2lscnN1cXZ6dnRvfHaYk5OhmnqAg4J7g32BhIN+i4KIpqGkoKqAg4Z+gX55foR6gXl8gZiblpZzcnR3c2xwdGdwam1uaYeDh4iEW2NdV11WVVZSV1RPVEx1dXZzd1JVWVdXYmRlYGVhampph46MkYtucXRudnFzdXZ0d3x0dJmfnJt9ent7fIaCfId+gYWAgYeho6Wih398gnuCe3p3fH16fnaclJyZm3R2c3BwbHNvcGdqaGdtioeIioNlXWRgYmBfV1hUVFVPU3Z2d3R9U1taWFdfXF5bZF9lZmSGiIiObnFxdHB2cndxenl2d3iam5ydnn1+f4CBgoOEhYaHiImKqqmop6aEg4KBgH9+fXx7enl5eJiXlpWUcnFwb25tbGtqaWhnZmaGhYSDYWBfXl1cW1pZWFdWVVR2d3h5elpbXF1dXl9gYWJjZGVmiImKi4xsbW5vb3BxcnN0dXZ3eJqbnJ2efn+AgYKCg4SFhoeIiYmpqKenhIOCgoGAf359fHt6eXh3l5aVlHJxcG9vbm1sa2ppaGdmhoWEg4JgX15dXVxbWllYV1ZVVHd4eXl6WltcXV5fYGFiY2RlZmaJiouLjGxtbm9wcXJzdHV2d3h5m5ydnn1+f4CBgoOEhYaHiImKqqmop6aEg4KBgH9+fXx7enl5eJiXlpWUcnFwb25tbGtqaWhnZmaGhYSDgmBfXl1cW1pZWFdWVVRVd3h5elpbXF1dXl9gYWJjZGVmiImKi4xsbW5vb3BxcnN0dXZ3eJqbnJ2efn+AgYKCg4SFhoeIiYmpqKenpoOCgoGAf359fHt6eXh3l5aVlJRxcG9vbm1sa2ppaGdmZYWEg4JgX15dXVxbWllYV1ZVVHd4eXl6WltcXV5fYGFiY2RlZmaJiouLjGxtbm9wcXJzdHV2d3h5m5ydnp5+f4CBgoOEhYaHiImKiamop6aEg4KBgH9+fXx7enl5eJiXlpWUcnFwb25tbGtqaWhnZmaGhYSDgmBfXl1cW1pZWFdWVVRVd3h5entbXF1dXl9gYWJjZGVmZ4mKi4xsbW5vb3BxcnN0dXZ3eHmbnJ2efn+AgYKCg4SFhoeIiYmpqKenpoOCgoGAf359fHt6eXh3l5aVlJRxcG9vbm1sa2ppaGdmZYWEg4KCX15dXVxbWllYV1ZVVFV4eXl6WltcXV5fYGFiY2RlZmaJiouLjGxtbm9wcXJzdHV2d3h5m5ydnp5+f4CBgoOEhYaHiImKiamop6alg4KBgH9+fXx7enl5eHeXlpWUcnFwb25tbGtqaWhnZmaGhYSDgmBfXl1cW1pZWFdWVVRVd3h5entbXF1dXl9gYWJjZGVmZ4mKi4yNbW5vb3BxcnN0dXZ3eHmbnJ2efn+AgYKCg4SFhoeIiYmIqKenpoOCgoGAf359fHt6eXh3l5aVlJRxcG9vbm1sa2ppaGdmZYWEg4KCX15dXVxbWllYV1ZVVFV4eXl6e1tcXV5fYGFiY2RlZmZniouLjGxtbm9wcXJzdHV2d3h5m5ydnp5+f4CBgoOEhYaHiImKiamop6alg4KBgH9+fXx7enl5eHeXlpWUk3Fwb25tbGtqaWhnZmZlhYSDgmBfXl1cW1pZWFdWVVRVd3h5entbXF1dXl9gYWJjZGVmZ4mKi4yNbW5vb3BxcnN0dXZ3eHmbnJ2en3+AgYKDhIWGh4iJioqJqKempaSEg4KBgH9+fXx7e3p5eJWUk5JzcnJxcG9ubWxramlpaIOCgYB/YmFgYF9eXVxbWllYWFl0dXZ3eF9gYWJjZGVmZ2hpamtshYaHiIlyc3R1dnd4eXp7fH1+f5aXmJmEhYaHiImKi4yNjo+Qj6KhoJ+eiomIh4aFhIOCgoGAf36Pjo2Mi3l4d3Z1dHNycXBwb25tfHt6eXhoZ2ZlZGNiYWBfX15eX29wcHFkZWZnaGlqa2xtbm9wcXKAgYKCd3h5ent8fX5/gIGCg4SQkZKTlIqLjI2Oj5CRkpOUlZWUnJuamZiPjo2Mi4qJiYiHhoWEg4mIh4aFfn18e3p5eHh3dnV0c3J2dXRzbm1sa2ppaGdmZmVkY2RpaWprbGprbG1ub3BxcnN0dXZ3ent7fH19fn+AgYKDhIWGh4iJiouMjY6PkJGSk5SUlZaXmJmamZiXlpWUlJOSkZCPjo2Mi4qJiIeGhYSDgoKBgH9+fXx7enl4d3Z1dHNycXBvb25tbGtqaWhnZmVmZmdoaWprbG1ub3BxcnN0dXZ3eHl5ent8fX5/gIGCg4SFhoeIiYqLi4yNjo+QkZKTlJWWl5iZmpqZmJeWlZSTkpGQj46NjIuLiomIh4aFhIOCgYB/fn18e3p5eXh3dnV0c3JxcG9ubWxramloZ2ZmZWZnaGlqa2xtbm9vcHFyc3R1dnd4eXp7fH1+f4CBgoKDhIWGh4iJiouMjY6PkJGSk5SUlZaXmJmamZiXlpWUlJOSkZCPjo2Mi4qJiIeGhYSDgoKBgH9+fXx7enl4d3Z1dHNycXBvb25tbGtqaWhnZmVmZmdoaWprbG1ub3BxcnN0dXZ3eHl5ent8fX5/gIGCg4SFhoeIiYqLi4yNjo+QkZKTlJWWl5iZmpqZmJeWlZSTkpGQj46NjIuLiomIh4aFhIOCgYB/fn18e3p5eXh3dnV0c3JxcG9ubWxramloZ2ZmZmhqZGRkZGRkZGNjY2OBg4VjY2NjY2NjY2NjYp2foWJiY2RlZmdoaWprrq+wb3BxcnN0dXZ3eHm6ubh3dnV1dHNycXBvbqyrqmtqaWhnZmVkY2Jin56dXl1cW1pZWFhXVlWRkI9RUE9PTk1MS0pJSIODhIVLTE1OT1BRUlNUj5CRkllaW1xdXl9gYWKcnZ6eZ2hpamtsbW5ub6ipqqt0dXZ3eHl6e3x9tbW0s3x7enl4d3Z1dHSop6alb25tbGtqamloZ5qZmJdiYWFgX15dXFtajIuKiVZVVFNSUVBPTk1Nfn+AT1BRUlNUVVZXWFmLjIxdXl9gYWJjZGVmZ5eYmWtsbW5vcHFyc3R1pKWmeXp7fH1+f4CBgoOxsK+BgH9+fXx8e3p5eKOioXRzc3JxcG9ubWxrlZSTaGdmZWRjYmFgX1+HhoVbWllYV1ZWVVRTUnl6entUVVZXWFlaW1xdhYaHiGJjZGVmZ2hpamuSk5SVcHFyc3R1dnd4eZ+goKF+f4CBgoOEhYaHq6uqqYWEhIOCgYB/fn2enZybeXh3dnV0c3JxcJGQj45sa2ppaGdmZWRjg4KCgV5dXVxbWllYV1ZVdnd4V1hZWltcXV5fYGGDhIVlZmZnaGlqa2xtbpCRknJzdHV2d3h5eXp7np6ff4CBgoOEhYaHiImrqqmHhoWEg4KBgH9+fZ6dnHl5eHd2dXRzcnFwkI+ObGtqaWhnZmZlZGODgoFfXl1cW1pZWFdWVXZ2d3hYWVpbXF1dXl9ggoOEhWVmZ2hpamtsbW6QkZKTcnN0dXZ3eHl6e52en6CAgYKCg4SFhoeIqqqpqIaFhIOCgoGAf36enZybeXh3dnV0c3JxcJGQj45sa2ppaGdmZWRjg4KCgV5dXVxbWllYV1ZVdnd4V1hZWltcXV5fYGGDhIVlZmZnaGlqa2xtbpCRknJzdHV2d3h5eXp7np6ff4CBgoOEhYaHiImrqqmHhoWEg4KBgH9+fZ6dnHl5eHd2dXRzcnFwkI+ObGtqaWhnZmZlZGODgoFfXl1cW1pZWFdWVXZ2d3hYWVpbXF1dXl9ggoOEhWVmZ2hpamtsbW6QkZKTcnN0dXZ3eHl6e52en6CAgYKCg4SFhoeIqqqpqIaFhIOCgoGAf36enZybeXh3dnV0c3JxcJGQj45sa2ppaGdmZWRjg4KCgV5dXVxbWllYV1ZVdnd4V1hZWltcXV5fYGGDhIVlZmZnaGlqa2xtbpCRknJzdHV2d3h5eXp7np6ff4CBgoOEhYaHiImrqqmHhoWEg4KBgH9+fZ6dnHl5eHd2dXRzcnFwkI+ObGtqaWhnZmZlZGODgoFfXl1cW1pZWFdWVXZ2d3hYWVpbXF1dXl9ggoOEhWVmZ2hpamtsbW6QkZKTcnN0dXZ3eHl6e52en6CAgYKCg4SFhoeIqqqpqIaFhIOCgoGAf36enZybeXh3dnV0c3JxcJGQj45sa2ppaGdmZWRjg4KCgV5dXVxbWllYV1ZVdnd4V1hZWltcXV5fYGGDhIVlZmZnaGlqa2xtbpCRknJzdHV2d3h5eXp7np6ff4CBgoOEhYaHiImrqqmHhoWEg4KBgH9+fZ6dnHl5eHd2dXRzcnFwkI+ObGtqaWhnZmZlZGODgoFfXl1cW1pZWFdWVXZ2d3hYWVpbXF1dXl9ggoOEhWVmZ2hpamtsbW6QkZKTcnN0dXZ3eHl6e52en6CAgYKCg4SFhoeIqqqpqIaFhIOCgoGAf36enZybeXh3dnV0c3JxcJGQj45sa2ppaGdmZWRjg4KCgV5dXVxbWllYV1ZVdnd4V1hZWltcXV5fYGGDhIVlZmZnaGlqa2xtbpCRknJzdHV2d3h5eXp7np6ff4CBgoOEhYaHiImrqqmHhoWEg4KBgH9+fZ6dnHl5eHd2dXRzcnFwkI+ObGtqaWhnZmZlZGODgoFfXl1cW1pZWFdWVXZ2d3hYWVpbXF1dXl9ggoOEhWVmZ2hpamtsbW6QkZKTcnN0dXZ3eHl6e52en6CAgYKCg4SFhoeIqqqpqIaFhIOCgoGAf36enZybeXh3dnV0c3JxcJGQj45sa2ppaGdmZWRjg4KCgV5dXVxbWllYV1ZVdnd4V1hZWltcXV5fYGGDhIVlZmZnaGlqa2xtbpCRknJzdHV2d3h5eXp7np6ff4CBgoOEhYaHiImrqqmHhoWEg4KBgH9+fZ6dnHl5eHd2dXRzcnFwkI+ObGtqaWhnZmZlZGODgoFfXl1cW1pZWFdWVXZ2d3hYWVpbXF1dXl9ggoOEhWVmZ2hpamtsbW6QkZKTcnN0dXZ3eHl6e52en6CAgYKCg4SFhoeIqqqpqIaFhIOCgoGAf36enZybeXh3dnV0c3JxcJGQj45sa2ppaGdmZWRjg4KCgV5dXVxbWllYV1ZVdnd4V1hZWltcXV5fYGGDhIVlZmZnaGlqa2xtbpCRknJzdHV2d3h5eXp7np6ff4CBgoOEhYaHiImrqqmHhoWEg4KBgH9+fZ6dnHl5eHd2dXRzcnFwkI+ObGtqaWhnZmZlZGODgoFfXl1cW1pZWFdWVXZ2d3hYWVpbXF1dXl9ggoOEhWVmZ2hpamtsbW6QkZKTcnN0dXZ3eHl6e52en6CAgYKCg4SFhoeIqqqpqIaFhIOCgoGAf36enZybeXh3dnV0c3JxcJGQj45sa2ppaGdmZWRjg4KBgF9eXVxbWllYV1ZWdXZ3WFlaW1xdXl9gYWKCgoNmZ2hpamtsbW5vcI6PkHR1dnd4eXp7fH1+m5ycgoOEhYaHiImKi4ynpqWKiomIh4aFhIOCgZmYl359fHt6eXh4d3Z1i4qJcXBvb25tbGtqaWh9fHtlZGNiYWBfXl1dXG9wcXJeX2BhYmNkZWZne3x9fmxtbm9wcXJzdHWIiYqLent8fX5/gIGCg5WVlpeIiYqLjI2Oj5CRoaGgn5CPjo2Mi4qJiIiUk5KRg4KBgH9/fn18e4aFhIN2dnV0c3JxcG9ueHd2dWppaGdmZWVkY2JhamprZGVmZmdoaWprbG12d3hxcnN0dXZ3eHl6e4OEhX+AgYKDhIWGh4iJj5CRjY6PkJGSk5SVlpecm5qWlZSTkpGQj4+OjY6NjImIh4eGhYSDgoGAgH9+fXx7enl4d3Z1dHNycXBvb25tbGtqaWhnZmVmZmdoaWprbG1ub3BxcnN0dXZ3eHl5ent8fX5/gIGCg4SFhoeIiYqLi4yNjo+QkZKTlJWWl5iZmpqZmJeWlZSTkpGQj46NjIuLiomIh4aFhIOCgYB/fn18e3p5eXh3dnV0c3JxcG9ubWxramloZ2ZmZWZnaGlqa2xtbm9vcHFyc3R1dnd4eXp7fH1+f4CBgoKDhIWGh4iJiouMjY6PkJGSk5SUlZaXmJmamZiXlpWUlJOSkZCPjo2Mi4qJiIeGhYSDgoKBgH9+fXx7enl4d3Z1dHNycXBvb25tbGtqaWhnZmVmZmdoaWprbG1ub3BxcnN0dXZ3eHl5ent8fX5/gIGCg4SFhoeIiYqLi4yNjo+QkZKTlJWWl5iZmpqZmJeWlZSTkpGQj46NjIuLiomIh4aFhIOCgYB/fn18e3p5eXh3dnV0c3JxcG9ubWxramloZ2ZmZWZnaGlqa2xtbm9vcHFyc3R1dnd4eXp7fH1+f4CBgoKDhIWGh4iJiouMjY6PkJGSk5SUlZaXmJmgpauwtbCztbe5uru8vLy7uri22tnX1dOgm5aQi4R+d3FqZF5YUo6Ig313MSwnIx8bGBUSEA4MCwtMTlBTVhkdISUqLzQ5PkNJTlRanqOorXR5foKGio6RlZeanJ6f3d7e3t6gn56dm5mXlZKPjYqHhLu2saynZ2JeWlVSTkpHREE/PTtzcnFwcDY2Nzc4Ojs9P0FDRUhKhYiKjVhaXWBiZWdpa21ucHFyqqyusLF8fX5/f39/f359fHt6eKyqqKakbWpoZmRhX11bWVdWVFOFhIOCgU5OTk5PT1BRU1RWWFtdj5CRkmJkZWdoamxucHJ0dnh6e62vsLKDhIWGh4iIiImIiIiHhrSysa+tfXt5d3Rxb2xpZmNfXFmEgoB/fU9OTEtKSEdGRUVEQ0NDbm5ubm5ERUZHSEpLTU9RU1VXWoaJi45oa25xdHd6fYGEh4qNkLq7vL2+lpeYmJiYmJiYmJeXlpW7ubi3tY2MioiGhIF/fXp4dXJwko+MiYZfXFpXVFFPTEpHRUJAPmFhYWE+Pz8/QEFCQ0RFRkdJSm5vcXN1VVhaXF5hY2Voam1vcnWYm56go4SGiYuOkJKUlpianJ6gwcHAwL+dnZybmpmYlpWUkpGPja2rqaeEgoB+e3l3dXJwbmxpZ2WDgX99WVdVU1FPTUtJR0VDQkBhYmJjY0NERUVGR0lKS0xOT1FSdXd4enxcXmBiZGZoamxucHN1d5qcnqCig4WHiYuNj5GSlJaYmZq7urq5mJeWlpWUk5KRkI+OjYyrqqmnpoOCgH59e3l4dnRycG9tjIqIhoRhYF5cWlhWVFNRT01LSmxsbG1tTE1NTU5PT1BQUVJTVFV3eHl6WltcXV5fYWJjZWZoaWuNj5GSlHR2d3l7fH6AgoOFh4iKq6urqqqJiIiIiIeHh4aGhYWEhKWko6OigIB/fn18fHt6eXh3dnWVlJOSkW5tbGppaGZlZGJhYF5egICBgWBhYWFiYmJjY2RkZGVlh4eHiIhnaGhpaWpqa2tsbG1tbpCQkZKScnNzdHV2dnd4eXp7fHycm5qZmXd2dXRzc3JxcHBvbm5tjo2NjGpqaWhoZ2dmZmVlZGRjhIODgoJgYF9fXl1dXFxbW1paWXx9f4CBYWJkZWZnaWprbG1ub3GTlJWWl3d4eXp7fH1+f4CBgoODpqanqIiJiYqLjIyNjo+QkJGSkbGvrq2LiYiHhoSDgoF/fn18epqZmJeVc3Jwb25ta2ppaGdlZGODgoB/flxaWVhXVlVTUlFQT05OcHFycnNTVFVVVldYWVpbW1xdXoCBgoNjZGVmZ2doaWprbHZ3eJqbnJ2efn+AgYKCg4SFhoeIiYmpqKenpoOCgoGAf359fHt6eXh3l5aVlJRxcG9vbm1sa2ppaGdmZYWEg4JgX15dXVxbWllYV1ZVVHd4eXl6WltcXV5fYGFiY2RlZmaJiouLjGxtbm9wcXJzdHV2d3h5m5ydnp5+f4CBgoOEhYaHiImKiamop6aEg4KBgH9+fXx7enl5eHeXlpWUcnFwb25tbGtqaWhnZmaGhYSDgmBfXl1cW1pZWFdWVVRVd3h5entbXF1dXl9gYWJjZGVmZ4mKi4yNbW5vb3BxcnN0dXZ3eHmbnJ2efn+AgYKCg4SFhoeIiYmpqKenpoOCgoGAf359fHt6eXh3l5aVlJRxcG9vbm1sa2ppaGdmZYWEg4KCX15dXVxbWllYV1ZVVFV4eXl6WltcXV5fYGFiY2RlZmaJiouLjGxtbm9wcXJzdHV2d3h5m5ydnp5+f4CBgoOEhYaHiImKiamop6alg4KBgH9+fXx7enl5eHeXlpWUk3Fwb25tbGtqaWhnZmZlhYSDgmBfXl1cW1pZWFdWVVRVd3h5entbXF1dXl9gYWJjZGVmZ4mKi4yNbW5vb3BxcnN0dXZ3eHmbnJ2en3+AgYKCg4SFhoeIiYmIqKenpoOCgoGAf359fHt6eXh3l5aVlJRxcG9vbm1sa2ppaGdmZYWEg4KCX15dXVxbWllYV1ZVVFV4eXl6e1tcXV5fYGFiY2RlZmZniouLjGxtbm9wcXJzdHV2d3h5eZydnp5+f4CBgoOEhYaHiImKiamop6alg4KBgH9+fXx7enl5eHeXlpWUk3Fwb25tbGtqaWhnZmZlhYSDgoFfXl1cW1pZWFdWVVRVVnh5entbXF1dXl9gYWJjZGVmZ4mKi4yNbW5vb3BxcnN0dXZ3eHmbnJ2en3+AgYKCg4SFhoeIiYmIqKenpqWCgoGAf359fHt6eXh3dpaVlJRxcG9vbm1sa2ppaGdmZYWEg4KCX15dXVxbWllYV1ZVVFV4eXl6e1tcXV5fYGFiY2RlZmZniouLjI1tbm9wcXJzdHV2d3h5eZydnp5+f4CBgoOEhYaHiImKiYiop6alg4KBgH9+fXx7enl5eHeXlpWUk3Fwb25tbGtqaWhnZmZlhYSDgoFfXl1cW1pZWFdWVVRVVnh5ent8XF1dXl9gYWJjZGVmZ2iKi4yNbW5vb3BxcnN0dXZ3eHmbnJ2en3+AgYKCg4SFhoeIiYmIqKenpqWCgoGAf359fHt6eXh3dpaVlJSTcG9vbm1sa2ppaGdmZWSEg4KCX15dXVxbWllYV1ZVVFV4eXl6e1tcXV5fYGFiY2RlZmZniouLjI1tbm9wcXJzdHV2d3h5eZydnp6ff4CBgoOEhYaHiImKiYinpqWko4OCgYB/f359fHt6eXh3lJOSkXNycXBvbm1tbGtqaWhngoGAf35iYWBfXl1cXFtaWVhYWXR1dnd4X2BhYmNkZWZnaGlqa2yFhoeIiXJzdHV2d3h5ent8fX5/l5eYmYSFhoeIiYqLjI2Oj4+PoqGgn56JiIeGhoWEg4KBgH9+fY+OjYyLeHd2dXV0c3JxcG9ubWx8e3p5eGdmZWRjY2JhYF9eXl9gb3BxcmVmZ2hpamtsbW5vcHFyc4CBgoN4eXp7fH1+f4CBgoOEhZCRkpOUi4yNjo+QkZKTlJWWlZScm5qZmI6OjYyLiomIh4aFhYSDiYiHhoV9fHx7enl4d3Z1dHNzcnZ1dHNtbGtqamloZ2ZlZGNkZWlqa2xta2xtbm9wcXJzdHV2d3h6e3x9fn5/gIGCg4SFhoeIiYqLi4yNjo+QkZKTlJWWl5iZmpqZmJeWlZSTkpGQj46NjIuLiomIh4aFhIOCgYB/fn18e3p5eXh3dnV0c3JxcG9ubWxramloZ2ZmZWZnaGlqa2xtbm9vcHFyc3R1dnd4eXp7fH1+f4CBgoKDhIWGh4iJiouMjY6PkJGSk5SUlZaXmJmamZiXlpWUlJOSkZCPjo2Mi4qJiIeGhYSDgoKBgH9+fXx7enl4d3Z1dHNycXBvb25tbGtqaWhnZmVmZmdoaWprbG1ub3BxcnN0dXZ3eHl5ent8fX5/gIGCg4SFhoeIiYqLi4yNjo+QkZKTlJWWl5iZmpqZmJeWlZSTkpGQj46NjIuLiomIh4aFhIOCgYB/fn18e3p5eXh3dnV0c3JxcG9ubWxramloZ2ZmZWZnaGlqa2xtbm9vcHFyc3R1dnd4eXp7fH1+f4CBgoKDhIWGh4iJiouMjY6PkJGSk5SUlZaXmJmamZiXlpWUlJOSkZCPjo2Mi4qJiIeGhYSDgoKBgH9+fXx7enl4d3Z1dHNycXBvb25tbGtqaWhnZmVnaGpsbmRkZGRkZGRkZGRkZGRjY2NjkpSVl5ljY2NjY2NkZWZnaGlqa2xtbrCxsrO0tXV2d3h5eXp5eHd2dXRzcnGwr66trKtramloZ2dmZWRjYmFgX15dXZmYl5aVV1ZVVFNTUlFQT05NTEtKSkmDg4SFhoZMTU5PUFFSU1RVVldYWVpblpeYmZmaYmNkZWZnaGlqa2xtbm9wcXKrrKytrnh5ent8fX5/fn18e3p5eXh3rKuqqaincG9vbm1sa2ppaGdmZWVkY5aVlJOSkVxcW1pZWFdWVVRTUlJRUE9Of35+f4BQUVJTVFVWV1hZWltcXV1eX5GRkpOUlWZnaGlqa2xtbm9wcXJzdHWkpaanqKl8fX5/gIGCg4OCgYGAf359fKempaSjd3Z1dHNycXBvbm5tbGtqaWiRkI+OjYxiYWBfXl1cW1paWVhXVlVUfHt6eXp7VFVWV1hZWltcXV5fYGFiY2SLjI2Oj2prbG1ub3BxcnN0dXZ3eHl6n6ChoqOkgYKDhIWGh4iJiIeGhYSDgqSjoqGgn3x7enl4d3Z2dXRzcnFwb25tjYyLi4pnZmZlZGNiYWBfXl1cW1pZWHl4d3Z2d1dYWVpbXF1dXl9gYWJjZGWHiImKi4xsbW5vb3BxcnN0dXZ3eHl6e52en6ChgYKCg4SFhoeIiYmIh4aFhIOko6KhoJ99fHt6eXh3dnV0c3JxcG9vj46NjIuKaGdmZWRjYmFgX15dXVxbWll5eHd2dlVWV1hZWltcXV5fYGFiY2Rlh4iJiotqa2xtbm9wcXJzdHV2d3h5eZydnp6foICBgoOEhYaHiImKiYiHhoWEpKOioaB+fXx7enl5eHd2dXRzcnFwb4+OjYyLaWhnZmZlZGNiYWBfXl1cW1p6eXl4d3ZVVldYWVpbXF1dXl9gYWJjZIaHiImKamtsbW5vb3BxcnN0dXZ3eHmbnJ2en3+AgYKCg4SFhoeIiYmIh4aFpqWko6Khf359fHt6eXh3dnV0c3JxcJGQj46NjGppaGdmZWRjYmFgX15dXVxbe3p5eHdVVFVWV1hZWltcXV5fYGFiY4WGh4iJimlqa2xtbm9wcXJzdHV2d3iam5ydnp5+f4CBgoOEhYaHiImKiYiHhqalpKOigH9+fXx7enl5eHd2dXRzcnGRkI+OjYxqaWhnZmZlZGNiYWBfXl1cfHt6eXl4VVRVVldYWVpbXF1dXl9gYWKEhYaHiGhpamtsbW5vb3BxcnN0dXZ3mZqbnJ2efn+AgYKCg4SFhoeIiYmIh6enpqWko4GAf359fHt6eXh3dnV0c3JxkpGQj45sa2ppaGdmZWRjYmFgX15dXX18e3p5eFZVVFVWV1hZWltcXV5fYGGDhIWGh4hnaGlqa2xtbm9wcXJzdHV2d5mam5ydfH1+f4CBgoOEhYaHiImKiYiop6alpKOBgH9+fXx7enl5eHd2dXRzk5KRkI+ObGtqaWhnZmZlZGNiYWBfXl19fHt6eVdWVVRVVldYWVpbXF1dXl9ggoOEhYaHZ2hpamtsbW5vb3BxcnN0dZeYmZqbnHx9fn+AgYKCg4SFhoeIiYmIqKenpqWCgoGAf359fHt6eXh3dnV0c5STkpGQj21sa2ppaGdmZWRjYmFgX15/fn18e3pYV1ZVVFVWV1hZWltcXV5fYIKDhIWGZmZnaGlqa2xtbm9wcXJzdHWXmJmam5x7fH1+f4CBgoOEhYaHiImKqqmop6alg4KBgH9+fXx7enl5eHd2dXSUk5KRkG5tbGtqaWhnZmZlZGNiYWBff359fHtZWFdWVVRVVldYWVpbXF1dXoGCgoOEhWVmZ2hpamtsbW5vb3BxcnN0lpeYmZp6e3x9fn+AgYKCg4SFhoeIiaqpqKenhIOCgoGAf359fHt6eXh3dnWVlJSTkpFvbm1sa2ppaGdmZWRjYmFgX4B/fn18WllYV1ZVVFVWV1hZWltcXV6AgYKDhGRlZmZnaGlqa2xtbm9wcXJzlZaXmJmaeXp7fH1+f4CBgoOEhYaHiKqrqqmop4WEg4KBgH9+fXx7enl5eHd2lpWUk5Jwb25tbGtqaWhnZmZlZGNiYYGAf359fFpZWFdWVVRVVldYWVpbXF1/gIGCgoNjZGVmZ2hpamtsbW5vb3BxcpSVlpeYeHl6e3x9fn+AgYKCg4SFhoepqqqpqKeFhIOCgoGAf359fHt6eXh3l5aVlJSTcG9vbm1sa2ppaGdmZWRjYmGCgYB/flxbWllYV1ZVVFVWV1hZWltcfn+AgYKDY2RlZmZnaGlqa2xtbm9wcZOUlZaXmHh5eXp7fH1+f4CBgoOEhYaHqaqrqqmHhoWEg4KBgH9+fXx7enl5eJiXlpWUk3Fwb25tbGtqaWhnZmZlZGODgoGAf35cW1pZWFdWVVRVVldYWVpbXH5/gIGCYWJjZGVmZ2hpamtsbW5vb3CTlJSVlpd3eHl6e3x9fn+AgYKCg4SFp6ipqqqph4aFhIOCgoGAf359fHt6eXiYl5aVlHJxcG9vbm1sa2ppaGdmZWRjg4KCgYB/XVxbWllYV1ZVVFVWV1hZWnx9fn+AgWFiY2RlZmZnaGlqa2xtbm9wkpOUlZZ2d3h5eXp7fH1+f4CBgoOEhaeoqaqrqoiHhoWEg4KBgH9+fXx7enmamZiXlpVzcnFwb25tbGtqaWhnZmZlZISDgoGAXl1cW1paWVhXVlVWV1hZWlt7fH1+fmFiY2RlZmdoaWprbG1ub3Bxj4+QkZKTeHl6e3x9fn+AgYKDhIWGh4ijpKWmp42Mi4qJiIeGhYWEg4KBgH9+lpWUk5J5eHd2dXRzc3JxcG9ubWxraoB/fn18e2RjYmJhYF9eXVxbW1xdXl9gdXZ2d3hmZ2hpamtsbW5vcHFyc3R1doiJiouMfH1+f4CBgoOEhYaHiImKi4ycnZ6foKGTkpGQj46NjIyLiomIh4aFhJGQj46Nf359fHt7enl4d3Z1dHNycnF7enl4d2tqaWloZ2ZlZGNiYWBhYmNkbm9vcHFya2xtbm9wcXJzdHV2d3h5eoGCg4SFhoGCg4SFhoeIiYqLjI2Oj5CRlpeYmZqXmJiXlpWUlJOSkZCPjo2Mi4yLiomIh4WEg4KCgYB/fn18e3p5eXh3dnV0c3JxcG9ubWxramloZ2ZmZWZnaGlqa2xtbm9vcHFyc3R1dnd4eXp7fH1+f4CBgoKDhIWGh4iJiouMjY6PkJGSk5SUlZaXmJmamZiXlpWUlJOSkZCPjo2Mi4qJiIeGhYSDgoKBgH9+fXx7enl4d3Z1dHNycXBvb25tbGtqaWhnZmVmZmdoaWprbG1ub3BxcnN0dXZ3eHl5ent8fX5/gIGCg4SFhoeIiYqLi4yNjo+QkZKTlJWWl5iZmpqZmJeWlZSTkpGQj46NjIuLiomIh4aFhIOCgYB/fn18e3p5eXh3dnV0c3JxcG9ubWxramloZ2ZmZWZnaGlqa2xtbm9vcHFyc3R1dnd4eXp7fH1+f4CBgoKDhIWGh4iJiouMjY6PkJGSk5SUlZaXmJmamZiXlpWUlJOSkZCPjo2Mi4qJiIeGhYSDgoKBgH9+fXx7enl4d3Z1dHNycXBvb25tbGtqaWhnZmVmZmdoaWprbG1ub3BxcnN0dXZ3eHl5ent8fX5/gIGCg4SFhoeIiYqLi4yNjo+QkZKTlJWWl5iZhp6onZSroo2JgYF3l6SEpZqZfXZng253fHSDg2Sahp+Xh5p/XFllRGFTUC9UTTxMVEwvNEQ+SzVAj5B/lZeZmlxIO0NTaU1JZUtxe01aaVRQV3ZvY7OSmJqqt7ZRf3NgUnJ4YnhqX2l2c2hgXnZhcoKsmbajp7KscGJicHVrb2F4f3F8ZWSDYId8hIBplbOnjaWQlHBLc29oY2peQVhaQ1VPPzdAUDFMM2t6i4R3gIVMSEJXPV5KYExMbVFnWFpdelxobn2gla+0sK2zcG9/b2qJh2xobollbGh8b3Bmf2V7iKejtLmirpFpe3hyel5kaXV6a2N9gGVpgYFncHyYlqKRi6aoX2ltd2FialRpUFFKV01cTFFbRlBWhIZ1eXx+dFVGWkNDUVNbZk1KYVlgXmxjdlhodZKUpp+YqJl9eXt6cnRwg42JfoB6eX2IdXl2ho2wuqCkmbCwh3Vtanx6b3FqdXFhaWZ2YmJoX2Zjj4uQmpaEk2JmbGtlYmpkW29ecWJXbFZaVV9OS3Zsd4B2eIBkS05SVltaVVRRalNpYW5hZV9oXWeLmoyNipqReGx2dYZyiHqBhn6PhJCTi4iLmISXiK+wo6aus6qAf4l9gIV9dHFtfnxwbWVsaXBxbWuNhZKHgJN7XWxlYGFZX2JaXWNnZF5aWWNdZVBXeniDgYCGfGlYV2lcZmNkaGlrY19aX2JrZGRpaYKMj5GIkIt5dnZ8enpyhXeAdYuMgIiNh4qUg5KxrK23r7CpgImMjHx/fYF1d4F6cX16enFubWplh4iDjIR/fWxqaGBpX2JnWF5fV1VXUlliXlVRV3+Ag3aCfoVWYVhgYWlnY2BubG5mbnFkbmxubmqHj5SPj4qKbHZyenh4fnd1gIB7g4aDhIOCg46LpLGwrqOxp6qHhn2KioiHgYOAdXx8dn5veHl0dHeOjJCMiI6MX2dlXGVZWFxXXlNeW1dVVllOVlZSdHB7cXKAd1tXYFxoaV9nYWhmZ2dobG1wb2lscpSWkpebl5VvfHZ3cnKAeXqAg4J7g32BhIN+i4KppqGkoKqig4Z+gX55foR6gXl8gXd6dXVzcnR3lI2RlYiRi21uaWZhZmdjW2NdV11WVVZSV1RPVG51dXZzd3NVWVdXYmRlYGVhamppZWxqcGpucXSQl5KVlpeVd3x0dHh+e3p9ent7fIaCfId+gYWAgaiho6WiqKB8gnuCe3p3fH16fnZ7c3t4eXR2c3CRjZWQkYiLaGdtaWVnaGJlXWRgYmBfV1hUVFVPdHZ2d3R9dFtaWFdfXF5bZF9lZmRlZ2dtbnFxdJGXk5iTm5p2d3h4eXp7fH1+f4CBgoOEhYaHiImrqqmop6alg4KBgH9+fXx7enl4d3d2dXRzcnFwkI+OjYyMi2hoZ2ZlZGNiYWBfXl1cW1taWVhXVnZ3eHl5entbXF1eX2BhYmJjZGVmZ2hpamtsbW6QkZKTk5SVdXZ3eHl6e3t8fX5/gIGCg4SFhYaHqamoqKempaSCgYB/fn18e3p5eXh3dnV0c3JxcG+Qj46NjIuKaGdmZWVkY2JhYF9eXVxcW1pZWFdWd3h5ent7fFxdXl9gYWJiY2RlZmdoaWpra2xtbpCRkpOUlZZ1dnd4eXp7e3x9fn+AgYKDg4SFhoepqKempqWkgoGAf359fHt7enl4d3Z1dHNzcnFwkI+Ojo2Mi2loZ2ZlZGRjYmFgX15dXVxbWllYV3h4eXp7fH1cXV5fYGFhYmNkZWZnaGhpamtsbW6QkZKSk5SVdXV2d3h5ent8fH1+f4CBgoKDhIWGqKinpqWkpKOBgH9+fXx7e3p5eHd2dXV0c3JxcG+Qj46NjIyLaWhnZmVkZGNiYWBfXl5dXFtaWVlYeHl6e3x9fl1eX2BhYWJjZGVmZ2doaWprbGxtbpCRkpOUlJV1dnd3eHl6e3x8fX5/gIGBgoOEhYaop6alpKOjgIB/fn18e3t6eXh3dnZ1dHNycXFwkI+Pjo2Mi2loaGdmZWRjY2JhYF9fXl1cW1paWXl6e3t8fX5dXl9gYWJiY2RlZmZnaGlqa2tsbW6QkZGSk5SVdHV2d3d4eXp7fHx9fn+AgIGCg4SEpqampaSjoqF/f359fHt7enl4d3d2dXRzc3JxcG+Qj46NjYyLaWhnZ2ZlZGNjYmFgYF9eXVxcW1pZent8fH1+f15fYGFiYmNkZWZmZ2hpaWprbG1tbpCRkpOTlJV0dXZ3eHh5ent7fH1+f3+AgYKCg4SmpaSko6Khf39+fXx7e3p5eHh3dnV0dHNycXFwkI+Pjo2MjGppaGdnZmVkY2NiYWBgX15dXVxbWnt7fH1+fn9fX2BhYmJjZGVlZmdoaWlqa2xsbW6QkZGSk5SUdHV1dnd4eHl6e3t8fX5+f4CBgYKDhKWko6OioaB+fn18e3t6eXh4d3Z1dXRzcnJxcG+Qj46OjYyLaWloZ2ZmZWRkY2JhYWBfXl5dXFtbfHx9fn9/gGBgYWJjY2RlZWZnaGhpamtrbG1ubpCRkpKTlJV0dXZ2d3h4eXp7e3x9fX5/gICBgoOkpKOioqGgfn19fHt6enl4eHd2dXV0c3NycXBwkI+Pjo2NjGppaWhnZmZlZGRjYmFhYF9fXl1dXHx9fX5/gIBgYGFiY2NkZWVmZ2hoaWpqa2xtbW6QkZGSk5OUdHR1dnZ3eHh5ent7fH1+fn+AgYGCo6OioaCgn55+fn18fHt6enl4eHd3dnV1dHNzcnGOjYyMi4qJbGxramppaWhnZ2ZlZWRjY2JiYWBgenp7e3x9fWVlZmdoaGlqamtsbW1ub3BwcXJyc4uMjI2Ojo95enp7fH19fn9/gIGCgoOEhIWGh4ednJuampmYhIOCgoGBgH9/fn19fHx7enp5eXh3iIiHhoaFhHJycXFwb29ubm1sbGtramlpaGhnZnV1dnZ3d3hra2xtbW5vb3BxcnJzdHR1dnZ3eHmFhoaHiIiJfn+AgIGCgoOEhIWGhoeIiImKi4uMlpaVlJSTkpKIiIeHhoaFhISDg4KBgYCAf35+fX2CgoGAgH9+eHd3dnZ1dXRzc3JycXFwb29ubm1tcHBxcnJzc3FycnN0dXV2d3d4eXl6e3t8fX1+f4CAgYKCg4OEhYWGhoeIiImJiouLjIyNjo6Pj5CRkI+Pjo6NjIyLi4qJiYiHh4aGhYSEg4OCgYGAgH9+fn19fHt7enp5eHh3d3Z1dXR0c3JycXFwb29vcHBxcnJzc3R1dXZ2d3h4eXl6e3t8fH1+fn9/gICBgoKDg4SFhYaGh4iIiYmKiouMjI2Njo6PkJCPjo6NjYyMi4qKiYmIh4eGhoWEhIODgoKBgIB/f35+fXx8e3t6enl4eHd3dnZ1dHRzc3JycXBwcHBxcXJyc3R0dXV2dnd4eHl5enp7fHx9fX5+f4CAgYGCgoOEhIWFhoaHh4iJiYqKi4uMjI2Ojo+Pj46NjYyMi4uKiomIiIeHhoaFhYSDg4KCgYGAgH9+fn19fHx7e3p6eXh4d3d2dnV1dHRzc3JxcXBxcXJyc3N0dHV2dnd3eHh5eXp6e3x8fX1+fn9/gICBgYKDg4SEhYWGhoeHiIiJiYqKi4uMjY2Ojo6OjY2Mi4uKiomJiIiHh4aGhYWEg4OCgoGBgIB/f35+fX18fHt7enp5eXh4d3d2dXV0dHNzcnJxcnR1d3hubW1sbGtramppaWhoZ2dmZpSVl5iaY2JiYWFgYWFiY2NkZGVlZmaoqamqqqtqa2tsbG1tbWxsbGtramppqKinp6amZmZlZWRkY2NiYmFhYWBgX1+cm5uamlxcW1taWllZWVhYV1dWVlVVkJCQkJGRV1dYWFlZWlpbW1xcXV5eX5mZmpqbm2JjY2RkZWVmZmdnaGhpampro6OkpKVubm9vcHBxcXFxcHBwb29ubqOjoqKhoWtqamlpaWhoZ2dmZmZlZWSYl5eWlpVhYWFgYF9fX15eXV1cXFxbW4yMjIyMW1xcXV1eXl9fYGBhYWJiY2OUlJWVlpZnZ2hoaWlqamtrbGxtbW5unZ2enp+fcnJzc3R0dXV2dXV0dHRzc3Kenp2dnHBvb29ubm1tbWxsa2tramppk5OSkpGRZ2ZmZmVlZGRkY2NiYmJhYYmIiIiIiGFhYmJjY2RkZGVlZmZnZ2hoj5CQkJFrbGxsbW1ubm9vcHBxcXJyc5eYmJmZmXZ2d3d4eHl5eXl5eXh4eHeZmZiYmJd1dHRzc3NycnJxcXBwcG9vbo+Pjo6NbGtra2pqaWlpaGhnZ2dmZmWGhoWFhYVkZWVmZmZnZ2hoaWlpamprjI2NjY6ObW5ub29vcHBxcXFycnJzc3SVlpaWl3Z2d3d4eHh5eXl6eXl5eHh3mJiYl5eWdXR0dHNzcnJycXFwcHBvb5CPj4+OjmxsbGtrampqaWloaGhnZ2dmh4eGhoZlZWVmZmZnZ2hoaGlpampqa4yNjY2ObW1ubm5vb29wcHFxcXJycnOUlZWVlpZ1dnZ2d3d3eHh5eXl5eHh3d5iYl5eWdXV0dHNzc3JycnFxcXBwb2+QkI+Pj21tbGxsa2tramppaWloaGhniIiIh4eHZWZmZmdnZ2hoaGlpaWpqamuMjY2Njm1tbm5ub29vcHBwcXFxcnJylJSVlZV0dXV1dnZ2d3d3eHh4eHh3d5iXl5eWlnV0dHRzc3NycnJxcXFwcHCQkJCPj49tbW1sbGxra2tqamppaWloaImJiIiIZmZmZmdnZ2hoaGlpaWpqamuMjY2NjY5tbW5ubm5vb29wcHBxcXFyk5OUlJSVdHR0dXV1dnZ2dnd3d3d3d3aXl5eWlnV0dHRzc3NycnJycXFxcHBwkZCQkI+Pbm1tbWxsbGxra2tqamppaYqKiomJiWdnZ2dnaGhoaWlpaWpqamtrjI2NjY5tbW1tbm5ub29vcHBwcHFxcZOTk5SUlHNzdHR0dXV1dXZ2dnZ3dnaXl5eWlpZ0dHRzc3NzcnJycXFxcXBwcJGQkJCQbm5ubW1tbGxsbGtra2tqamqLi4qKioloaGdoaGhoaWlpampqamtrjI2NjY2ObW1tbW5ubm9vb29wcHBwcXGSk5OTk3Jzc3NzdHR0dHV1dXV2dnZ2l5aWlpaVdHRzc3NzcnJycnFxcXFwcJGRkZCQkG5ubm5tbW1tbGxsbGtra2tqi4uLi4tpaWloaGhpaWlpampqamtra42NjY2Ojm1tbW5ubm5ub29vb3BwcHCSkpKSk5NycnJzc3Nzc3R0dHR1dXV1dZaWlZWVdHNzc3NycnJycnFxcXFwcHCRkZGQkJBubm5ubm1tbW1tbGxsbGxrjIyMjIuLamppaWlpaWpqampqa2tra2uNjY2Ojm1tbW1ubm5ubm9vb29vcHBwkZKSkpKScXJycnJyc3Nzc3N0dHR0dJaVlZWVlXNzc3NycnJycnFxcXFxcHBwkZGRkJBvb25ubm5ubm1tbW1tbGxsbI2NjYyMa2tqampqampqamtra2tra2yNjY2Ojo5tbW1tbm5ubm5vb29vb29wcJGRkpKScXFxcXFycnJycnJzc3Nzc3OVlZWUlHNzcnJycnJycXFxcXFxcHBwkZGRkZCQb29vbm5ubm5ubW1tbW1tbWyNjY2NjWtra2tra2tra2tra2tsbGxsjY6Ojo5tbW1tbm5ubm5ub29vb29vb5GRkZGRknBxcXFxcXFxcnJycnJycnOUlJSUlJRycnJycnFxcXFxcXFwcHBwcJGRkZGQb29vb29ubm5ubm5ubm1tbW2Ojo6Ojo1sbGxsbGxra2tsbGxsbGxsjo6Ojo6ObW1ubm5ubm5ubm9vb29vb2+RkZGRkXBwcHBwcXFxcXFxcXFxcnJyk5OTk5OTcnFxcXFxcXFxcXBwcHBwcJGRkZGRkG9vb29vb25ubm5ubm5ubm5tj46Ojo5tbW1tbGxsbGxsbGxsbW1tbY6Ojo+Pj25ubm5ubm5ubm5vb29vb2+QkJGRkZFwcHBwcHBwcHBwcXFxcXFxcZKSkpKScXFxcXFxcXBwcHBwcHBwcHCRkZGRkJBvb29vb29vb25ubm5ubm5uj4+Pj4+PbW1tbW1tbW1tbW1tbW1tbW2Pj4+Pj25ubm5ubm5ubm9vb29vb29vkJCQkJCRb29wcHBwcHBwcHBwcHBwcJKSkpKSknBwcHBwcHBwcHBwcHBwcG9vkZGQkJBvb29vb29vb29vb29vbm5ubo+Pj4+Pj25ubm5ubm5ubm5ubm5ubm6Pj4+Pj49ubm5ubm5vb29vb29vb29vb5CQkJCQb29vb29vb29vb29vcHBwcHCRkZGRkZFwcHBwcHBvb29vb29vb29vkJCQkJCQb29vb29vb29vb29vb29vb2+QkJCQkG9vb29vb29vb29vb29vb29vj4+Pj49wcHBwcHBwcHBxcXFxcXFxcY6Ojo6OjnFxcXJycnJycnJycnJycnJyjY2NjY1zc3Nzc3Nzc3Nzc3Nzc3Nzc4yMjIyMdHR0dHR0dHR0dHR0dHR0dHSLi4uKiop1dXV1dXV1dXV1dXV1dXV1domJiYmJdnZ2dnZ2dnZ2dnZ2dnZ3d3eIiIiIiHd3d3d3d3d3d3d3d3h4eHh4h4eHh4eHeHh4eHh4eHh4eXl5eXl5eXmGhoaGhnl5eXl5eXl6enp6enp6enp6hYWFhYV6enp6e3t7e3t7e3t7e3t7e4SEhISEhHt8fHx8fHx8fHx8fHx8fHyDg4ODg4J9fX19fX19fX19fX19fX19fYKCgYGBfn5+fn5+fn5+fn5+fn5+fn6AgICAgIB/f39/f39/f39/f39/gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIA=",
}


def play_sound(name, loop=False):
    """Plays a sound effect or looping bgm in a tiny iframe via components.html.

    One-shot SFX (loop=False): each call embeds a unique comment so the
    iframe's HTML content differs every time, forcing a genuine reload -
    otherwise the browser reuses the existing <audio> element in place and
    the 2nd, 3rd, etc. play of the same sound stays silent.

    Looping BGM (loop=True): the opposite is needed here. This is called
    again on every single rerun (any click anywhere reruns the whole
    script), so the HTML must stay byte-identical across calls. That way
    Streamlit sees unchanged content and leaves the existing iframe alone
    instead of reloading it - which is what was making the music jump back
    to 0:00 every time something was clicked.
    """
    loop_attr = "loop" if loop else ""
    if loop:
        marker = ""  # unchanging content -> iframe is never reloaded -> bgm keeps playing
        # Browsers block autoplay until the *page* has registered a genuine
        # user gesture. The very first time this component appears (right
        # after login, when the page flips away from "auth"), the iframe is
        # created by an async Streamlit rerun rather than as the direct,
        # synchronous result of a click, so autoplay silently fails and the
        # <audio> element just sits there paused - that's what made bgm stay
        # dead until the sidebar checkbox was toggled off/on (that toggle IS
        # a direct click, so it works). Fix: if .play() is rejected, don't
        # give up - listen for the *next* click anywhere in the app (on the
        # parent document, since this iframe itself is invisible/height:0)
        # and retry then. That way bgm quietly starts the moment the player
        # clicks anything at all, instead of requiring that one specific
        # checkbox.
        retry_script = """
        <script>
        (function() {
            var a = document.querySelector('audio');
            if (!a) return;
            function tryPlay() { a.play().catch(function() {}); }
            var p = a.play();
            if (p !== undefined) {
                p.catch(function() {
                    function retryOnce() {
                        tryPlay();
                    }
                    try {
                        window.parent.document.addEventListener('click', retryOnce, {once: true});
                    } catch (e) {}
                    document.addEventListener('click', retryOnce, {once: true});
                });
            }
        })();
        </script>
        """
    else:
        st.session_state.audio_seq += 1
        marker = f"<!-- seq:{st.session_state.audio_seq} -->"
        retry_script = ""
    components.html(
        f'''
        <audio autoplay {loop_attr} style="display:none">
            <source src="data:audio/wav;base64,{AUDIO_B64[name]}" type="audio/wav">
        </audio>
        {marker}
        {retry_script}
        ''',
        height=0,
    )


# =========================================================
# THEME (cyberpunk neon) + ANIMATIONS
# =========================================================

def inject_theme():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap');

        @keyframes bgDrift {
            0%   { background-position: 0% 0%, 100% 100%, 50% 50%; }
            50%  { background-position: 10% 6%, 92% 94%, 55% 46%; }
            100% { background-position: 0% 0%, 100% 100%, 50% 50%; }
        }
        .stApp {
            background-image:
                radial-gradient(circle at 20% 10%, rgba(0, 255, 242, 0.10) 0%, transparent 22%),
                radial-gradient(circle at 85% 85%, rgba(255, 43, 214, 0.10) 0%, transparent 25%),
                radial-gradient(circle at 50% 50%, #14213d 0%, #060a12 55%, #030509 100%);
            background-size: 200% 200%, 200% 200%, 130% 130%;
            animation: bgDrift 18s ease-in-out infinite;
            color: #e6f7ff;
        }

        @keyframes pageFadeIn {
            0%   { opacity: 0; transform: translateY(6px); }
            100% { opacity: 1; transform: translateY(0); }
        }
        [data-testid="stAppViewContainer"] > .main .block-container {
            animation: pageFadeIn 0.35s ease-out;
        }

        @keyframes titleFlicker {
            0%, 19%, 21%, 100% { text-shadow: 0 0 8px rgba(0, 255, 242, 0.55), 0 0 18px rgba(0, 255, 242, 0.25); }
            20% { text-shadow: 0 0 2px rgba(0, 255, 242, 0.2); }
        }
        h1, h2, h3 {
            font-family: 'Courier New', monospace;
            text-shadow: 0 0 8px rgba(0, 255, 242, 0.55);
        }
        h1 {
            font-family: 'Press Start 2P', 'Courier New', monospace;
            font-size: 1.4rem !important;
            line-height: 1.6 !important;
            animation: titleFlicker 6s ease-in-out infinite;
        }

        [data-testid="stMetric"] {
            background: rgba(0, 255, 242, 0.06);
            border: 1px solid rgba(0, 255, 242, 0.35);
            border-radius: 10px;
            padding: 10px 6px;
            transition: box-shadow 0.2s ease;
        }
        [data-testid="stMetric"]:hover {
            box-shadow: 0 0 14px rgba(0, 255, 242, 0.35);
        }
        [data-testid="stMetricValue"] {
            color: #00fff2;
            text-shadow: 0 0 6px rgba(0, 255, 242, 0.7);
        }

        .stButton > button {
            background: linear-gradient(135deg, #ff2bd6 0%, #7b2ff7 100%);
            color: #ffffff;
            border: 1px solid rgba(255, 43, 214, 0.6);
            border-radius: 8px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            letter-spacing: 0.5px;
            transition: all 0.15s ease-in-out;
            box-shadow: 0 0 10px rgba(255, 43, 214, 0.25);
        }
        .stButton > button:hover {
            box-shadow: 0 0 16px rgba(255, 43, 214, 0.65);
            transform: translateY(-1px);
            border-color: #ff2bd6;
        }
        .stButton > button:active {
            transform: translateY(0px) scale(0.98);
        }

        .stTextInput input, .stTextArea textarea {
            background-color: #0d1321 !important;
            color: #39ff14 !important;
            font-family: 'Courier New', monospace !important;
            border: 1px solid rgba(57, 255, 20, 0.4) !important;
            border-radius: 6px !important;
        }

        code, .stMarkdown code {
            color: #39ff14 !important;
        }
        [data-testid="stCodeBlock"] {
            border: 1px solid rgba(57, 255, 20, 0.35);
            border-radius: 8px;
            box-shadow: 0 0 12px rgba(57, 255, 20, 0.08);
        }

        .level-card {
            border-radius: 10px;
            padding: 14px 16px;
            margin-bottom: 8px;
            font-family: 'Courier New', monospace;
            border: 1px solid;
        }
        .level-done {
            background: rgba(57, 255, 20, 0.08);
            border-color: rgba(57, 255, 20, 0.5);
            color: #39ff14;
        }
        .level-open {
            background: rgba(0, 255, 242, 0.06);
            border-color: rgba(0, 255, 242, 0.45);
            color: #00fff2;
        }
        .level-locked {
            background: rgba(255, 255, 255, 0.03);
            border-color: rgba(255, 255, 255, 0.12);
            color: #6b7280;
        }

        /* Level-select buttons ARE the level cards (one clickable element, no
           separate "Play" button). Color/behavior reflects level status via
           the widget key (see levels page), matched with an attribute
           substring selector so it degrades gracefully on older Streamlit. */
        div[class*="st-key-level_done"] button {
            background: rgba(57, 255, 20, 0.08) !important;
            border: 1px solid rgba(57, 255, 20, 0.5) !important;
            color: #39ff14 !important;
            box-shadow: 0 0 8px rgba(57, 255, 20, 0.15) !important;
            font-size: 1.02rem;
            padding: 0.9em 1em !important;
        }
        div[class*="st-key-level_done"] button:hover {
            box-shadow: 0 0 18px rgba(57, 255, 20, 0.55) !important;
            transform: translateY(-2px);
        }

        @keyframes levelOpenPulse {
            0%, 100% { box-shadow: 0 0 8px rgba(0, 255, 242, 0.22); }
            50%      { box-shadow: 0 0 20px rgba(0, 255, 242, 0.6); }
        }
        div[class*="st-key-level_open"] button {
            background: rgba(0, 255, 242, 0.06) !important;
            border: 1px solid rgba(0, 255, 242, 0.5) !important;
            color: #00fff2 !important;
            font-size: 1.02rem;
            padding: 0.9em 1em !important;
            animation: levelOpenPulse 2.4s ease-in-out infinite;
        }
        div[class*="st-key-level_open"] button:hover {
            animation: none;
            box-shadow: 0 0 24px rgba(0, 255, 242, 0.8) !important;
            transform: translateY(-2px) scale(1.005);
        }

        div[class*="st-key-level_locked"] button {
            background: rgba(255, 255, 255, 0.02) !important;
            border: 1px solid rgba(255, 255, 255, 0.12) !important;
            color: #6b7280 !important;
            box-shadow: none !important;
            font-size: 1.02rem;
            padding: 0.9em 1em !important;
        }
        div[class*="st-key-level_locked"] button:hover {
            transform: none !important;
        }

        .hearts-row {
            text-align: center;
            font-size: 32px;
            margin: 10px;
        }
        .heart {
            display: inline-block;
            text-shadow: 0 0 10px rgba(255, 43, 109, 0.7);
        }
        @keyframes heartPop {
            0%   { transform: scale(1); }
            30%  { transform: scale(1.6) rotate(-8deg); }
            60%  { transform: scale(0.7) rotate(6deg); }
            100% { transform: scale(1); }
        }
        .heart-pop {
            animation: heartPop 0.45s ease;
        }

        @keyframes shakeCard {
            0%, 100% { transform: translateX(0); }
            20%      { transform: translateX(-8px); }
            40%      { transform: translateX(8px); }
            60%      { transform: translateX(-6px); }
            80%      { transform: translateX(6px); }
        }
        .shake-feedback {
            animation: shakeCard 0.4s ease;
        }

        @keyframes glowPulse {
            0%   { box-shadow: 0 0 6px rgba(57, 255, 20, 0.3); }
            50%  { box-shadow: 0 0 26px rgba(57, 255, 20, 0.85); }
            100% { box-shadow: 0 0 6px rgba(57, 255, 20, 0.3); }
        }
        .glow-feedback {
            border-radius: 10px;
            animation: glowPulse 0.9s ease;
        }

        @keyframes confettiPop {
            0%   { transform: translateY(0) scale(0.5) rotate(0deg); opacity: 0; }
            20%  { opacity: 1; }
            100% { transform: translateY(-40px) scale(1.2) rotate(25deg); opacity: 0; }
        }
        .confetti-row {
            text-align: center;
            font-size: 28px;
            height: 40px;
        }
        .confetti-row span {
            display: inline-block;
            animation: confettiPop 0.9s ease forwards;
        }

        @keyframes mascotIn {
            0%   { opacity: 0; transform: translateX(-6px); }
            100% { opacity: 1; transform: translateX(0); }
        }
        .mascot-bubble {
            display: flex;
            align-items: center;
            gap: 10px;
            background: rgba(0, 255, 242, 0.06);
            border: 1px solid rgba(0, 255, 242, 0.35);
            border-left: 4px solid #00fff2;
            border-radius: 8px;
            padding: 10px 14px;
            margin: 8px 0 14px 0;
            font-family: 'Courier New', monospace;
            animation: mascotIn 0.3s ease-out;
        }
        .mascot-avatar {
            font-size: 22px;
            flex-shrink: 0;
        }
        .mascot-text {
            color: #e6f7ff;
            line-height: 1.4;
        }
        .mascot-text b {
            color: #00fff2;
        }

        .sector-banner {
            font-family: 'Courier New', monospace;
            border: 1px solid rgba(255, 43, 214, 0.4);
            border-radius: 8px;
            padding: 10px 14px;
            margin-bottom: 10px;
            background: rgba(255, 43, 214, 0.05);
        }
        .sector-banner .sector-tag {
            color: #ff2bd6;
            letter-spacing: 1px;
            font-size: 0.8rem;
        }
        .sector-banner .sector-tagline {
            color: #a9b7c6;
            font-size: 0.9rem;
        }

        @keyframes bossPulse {
            0%   { box-shadow: 0 0 8px rgba(255, 43, 43, 0.35); }
            50%  { box-shadow: 0 0 22px rgba(255, 43, 43, 0.75); }
            100% { box-shadow: 0 0 8px rgba(255, 43, 43, 0.35); }
        }
        .boss-banner {
            font-family: 'Courier New', monospace;
            border: 1px solid rgba(255, 43, 43, 0.6);
            border-radius: 10px;
            padding: 14px 16px;
            margin-bottom: 10px;
            background: rgba(255, 43, 43, 0.06);
            animation: bossPulse 2.4s ease-in-out infinite;
        }
        .boss-banner .boss-tag {
            color: #ff3b3b;
            letter-spacing: 1px;
            font-size: 0.8rem;
        }
        .boss-banner .boss-title {
            color: #ffd166;
            font-size: 1.3rem;
            font-weight: bold;
            margin: 2px 0;
        }
        .boss-banner .boss-tagline {
            color: #e6b8b8;
            font-size: 0.9rem;
        }

        .achievement-badge {
            font-family: 'Courier New', monospace;
            display: inline-block;
            border: 1px solid rgba(0, 255, 242, 0.4);
            border-radius: 8px;
            padding: 8px 12px;
            margin: 4px 6px 4px 0;
            background: rgba(0, 255, 242, 0.06);
        }
        .achievement-badge.locked {
            border-color: rgba(255, 255, 255, 0.15);
            background: rgba(255, 255, 255, 0.02);
            opacity: 0.55;
        }
        .achievement-badge .a-title {
            font-weight: bold;
            color: #00fff2;
        }
        .achievement-badge.locked .a-title {
            color: #8a94a3;
        }
        .achievement-badge .a-desc {
            display: block;
            color: #a9b7c6;
            font-size: 0.8rem;
        }

        @keyframes badgePop {
            0%   { transform: scale(0.6); opacity: 0; }
            60%  { transform: scale(1.08); opacity: 1; }
            100% { transform: scale(1); opacity: 1; }
        }
        .achievement-unlock-toast {
            font-family: 'Courier New', monospace;
            border: 1px solid #ffd166;
            border-radius: 8px;
            padding: 10px 14px;
            margin: 8px 0;
            background: rgba(255, 209, 102, 0.08);
            animation: badgePop 0.5s ease;
        }
        </style>
        """,
        unsafe_allow_html=True
    )


# =========================================================
# SESSION STATE
# =========================================================

def init_state():
    # Land straight on the home page as a guest. Nobody should have to clear
    # a login form before they've seen a single second of the actual game -
    # that's the single biggest thing killing first-impression "hook." The
    # sign-up prompt now happens contextually (after finishing a level, or
    # anytime from the sidebar) instead of being a wall in front of everything.
    defaults = {
        "page": "home",
        "username": "Guest",
        "is_guest": True,
        "topic": None,
        "lesson_page": 0,
        "level": 1,
        "xp": 0,
        "rating": GUEST_STARTING_RATING,
        "completed_levels": {t: [] for t in ALL_TOPICS},
        "health": 3,
        "max_health": 3,
        "challenge_finished": False,
        "shuffled_blocks": [],
        "attempt_id": 0,          # bumped on every wrong answer so each
                                   # attempt's widgets get a fresh, unique key
        "level_start_time": None, # time.time() when the current level began
        "audio_seq": 0,
        "sfx_on": True,
        "bgm_on": True,
        "last_event": None,   # "correct" / "wrong" / "gameover" / None
        "level_won": False,   # persists across reruns, unlike last_event above
        "last_event_info": {},
        "confirm_reset": False,   # gates the destructive "Reset Progress" button
        "seen_signup_nudge": False,  # so the post-level signup nudge only ever fires once per session
        "auth_view": "login",  # which tab the auth page opens on - "login" or "signup"
        "achievements": [],        # unlocked achievement ids, persisted for real accounts
        "streak_count": 0,         # consecutive calendar days played
        "longest_streak": 0,
        "last_play_date": None,    # ISO date string, used to advance/reset streak_count
        "had_perfect_run": False,  # ever finished a node with zero hearts lost
        "had_speed_run": False,    # ever finished a node in under 10s
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# =========================================================
# RATING SYSTEM
# =========================================================

def get_max_health(level):
    return 3 if level <= 5 else 5


def get_win_rating(level, hearts_left):
    if level <= 5:
        rewards = {3: 20, 2: 15, 1: 10}
    else:
        rewards = {5: 40, 4: 35, 3: 30, 2: 25, 1: 20}
    return rewards.get(hearts_left, 0)


def get_loss_rating(level):
    return 10 if level <= 5 else 20


# =========================================================
# TIME-BASED SCORING
# ---------------------------------------------------------
# Every level has an XP "speed bonus" pool that starts full and drains by
# 1 XP per second spent on the level, down to a floor of 0. Harder levels
# (higher level number) get a bigger pool, since they're expected to take
# longer to read and solve - so the bonus stays a meaningful, fair reward
# rather than something only fast typists can ever earn.
# =========================================================

def get_time_bonus_pool(level):
    return 30 + level * 5


def get_time_bonus(level, elapsed_seconds):
    pool = get_time_bonus_pool(level)
    return max(0, pool - int(elapsed_seconds))


def get_rank(rating):
    if rating < 800:
        return "\U0001F331 Beginner"
    elif rating < 1000:
        return "\U0001F529 Novice"
    elif rating < 1200:
        return "\U0001F4BB Coder"
    elif rating < 1400:
        return "\u26A1 Advanced Coder"
    elif rating < 1600:
        return "\U0001F525 Python Expert"
    else:
        return "\U0001F451 Python Master"


def get_leaderboard(top_n=10):
    """Top N registered accounts by rating (ties broken by XP, then name).
    Guests never appear here since they're never written to the database."""
    users = get_all_users()
    entries = [
        {
            "username": data["username"],
            "rating": data.get("rating", 1000),
            "xp": data.get("xp", 0),
        }
        for data in users
    ]
    entries.sort(key=lambda e: (-e["rating"], -e["xp"], e["username"].lower()))
    return entries[:top_n]


def show_hearts(animate=None):
    """animate: None, 'pop' (just lost a heart) or 'gain' (level start reset)."""
    cells = []
    for i in range(st.session_state.max_health):
        filled = i < st.session_state.health
        cls = "heart"
        # animate the heart that was JUST lost (the first empty one from the left,
        # i.e. index == current health, since it flipped from full to empty)
        if animate == "pop" and i == st.session_state.health:
            cls += " heart-pop"
        symbol = "\u2764\uFE0F" if filled else "\U0001F5A4"
        cells.append(f'<span class="{cls}">{symbol}</span>')
    st.markdown(f'<div class="hearts-row">{"".join(cells)}</div>', unsafe_allow_html=True)


def show_confetti():
    emojis = ["\U0001F389", "\u2728", "\U0001F38A", "\u2B50", "\U0001F389"]
    spans = "".join(
        f'<span style="animation-delay:{i*0.07}s">{e}</span>'
        for i, e in enumerate(emojis)
    )
    st.markdown(f'<div class="confetti-row">{spans}</div>', unsafe_allow_html=True)


# =========================================================
# ANSWER NORMALIZATION
# =========================================================

def normalize_line(line):
    line = line.strip()
    line = re.sub(r"\s+", " ", line)
    line = re.sub(r"\'([^\'\"]*)\'", r'"\1"', line)
    return line


def normalize_code(code):
    return [
        normalize_line(l)
        for l in code.strip().split("\n")
        if l.strip() != ""
    ]


def check_drag_answer(user_order, expected):
    """expected can be a single ordering (list[str]) or a list of accepted
    orderings (list[list[str]]) when more than one arrangement is valid."""
    if expected and isinstance(expected[0], list):
        return user_order in expected
    return user_order == expected


def drag_feedback(user_order, expected):
    """Returns a short 'N of M blocks in the right spot' message against
    whichever accepted ordering the student is currently closest to -
    specific enough to be useful, without ever revealing the actual order."""
    accepted = expected if (expected and isinstance(expected[0], list)) else [expected]
    best = max(
        sum(1 for u, e in zip(user_order, ans) if u == e)
        for ans in accepted
    )
    total = len(user_order)
    return f"{best} of {total} blocks are in the right position."


def check_missing_line(user, expected):
    """Checks a single fill-in-the-blank line against its expected answer.

    `expected` is normally a plain string, matched exactly (after
    normalization). For blanks where the question deliberately leaves the
    value up to the student (e.g. "pick any whole number"), `expected` can
    instead be a string starting with "re:" followed by a regex that is
    matched against the whole normalized line — this lets any value that
    fits the required shape count as correct, not just one hard-coded
    example.
    """
    normalized_user = normalize_line(user)
    if expected.startswith("re:"):
        pattern = expected[3:]
        return re.fullmatch(pattern, normalized_user) is not None
    return normalized_user == normalize_line(expected)


# =========================================================
# LIGHTWEIGHT CODE SANDBOX (for "type the whole program" checks)
# =========================================================
# This lets Q10-style challenges accept ANY logically-correct program
# instead of requiring an exact character-for-character match: the
# student's code and the reference answer are both actually run (with
# fake input() values fed in) and their printed output is compared. Names,
# formatting, indentation style, or how the answer is computed don't
# matter as long as the behavior matches.
#
# Note: this is a *lightweight* sandbox meant to stop accidents (typos,
# infinite loops), not a hardened security boundary against a
# determined, malicious user. Only whitelisted builtins are exposed and
# a timeout guards against infinite loops, but Python sandboxing can
# never be fully airtight. Don't expose this app to untrusted users on
# sensitive infrastructure.

_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "dict", "enumerate", "False", "float",
    "int", "len", "list", "max", "min", "None", "print", "range", "round",
    "set", "sorted", "str", "sum", "True", "tuple", "zip",
)
SAFE_BUILTINS = {
    name: getattr(_builtins, name)
    for name in _SAFE_BUILTIN_NAMES
    if hasattr(_builtins, name)
}


def run_program_safely(code, inputs, timeout=3):
    """Executes `code` in a restricted environment, feeding `inputs` (a
    list of strings) to successive input() calls, and returns
    (success, output_or_error_message). Runs on a watchdog thread so an
    infinite loop in student code can't hang the app forever.

    Output is captured by overriding `print` directly rather than by
    redirecting sys.stdout: sys.stdout is a single global, so redirecting
    it would leak across threads, and a timed-out (abandoned) worker
    thread that never returns would permanently hijack the real app's
    output. Capturing via our own `print` avoids touching global state
    at all."""
    input_iter = iter(inputs)
    output_parts = []

    def fake_input(prompt=""):
        try:
            return next(input_iter)
        except StopIteration:
            raise EOFError("The program asked for more input than expected.")

    def fake_print(*args, sep=" ", end="\n", **kwargs):
        output_parts.append(sep.join(str(a) for a in args) + end)

    result = {}

    def target():
        safe_builtins = dict(SAFE_BUILTINS)
        safe_builtins["print"] = fake_print
        exec_globals = {"__builtins__": safe_builtins, "input": fake_input}
        try:
            exec(code, exec_globals)
            result["ok"] = True
        except Exception as e:
            result["ok"] = False
            result["error"] = f"{type(e).__name__}: {e}"

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return False, "Timed out (possible infinite loop)."
    if result.get("ok"):
        return True, "".join(output_parts)
    return False, result.get("error", "Unknown error.")


def normalize_output(text):
    """Normalizes printed output before comparing two programs' results.
    Case, punctuation, and spacing are cosmetic - two students who both
    got the logic right but wrote print("Hello", name) vs
    print(f"Hello, {name}!") shouldn't be graded differently just
    because one added a comma and an exclamation mark. The actual words
    and numbers printed still have to match, so an answer that prints
    "Child" instead of "Teenager" is still marked wrong."""
    text = text.lower()
    text = re.sub(r"[.,!?;:'\"]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def programs_behave_the_same(user_code, reference_code, test_cases):
    """Runs both programs against every input scenario in `test_cases`
    (a list of input lists) and checks their printed output matches each
    time, ignoring cosmetic formatting differences (see normalize_output).
    Variable names never factor in at all here, since only the printed
    output is compared, not the source code.

    Returns (correct, detail): detail is None when correct, otherwise a
    specific, non-answer-revealing reason - the student's own Python error
    if their code crashed, or which test input produced the wrong output -
    so a wrong answer is more useful than a bare "incorrect"."""
    if not (user_code or "").strip():
        return False, "You haven't written anything yet."
    for inputs in test_cases:
        ref_ok, ref_output = run_program_safely(reference_code, inputs)
        if not ref_ok:
            # Reference answer itself failed to run - treat as a config
            # problem, not the student's fault, and skip this case.
            continue
        user_ok, user_output = run_program_safely(user_code, inputs)
        if not user_ok:
            return False, f"Your code hit an error: {user_output}"
        if normalize_output(user_output) != normalize_output(ref_output):
            shown_input = ", ".join(inputs) if inputs else "(no input)"
            return False, f"Output didn't match for input: {shown_input}. Double-check your logic for that case."
    return True, None


# =========================================================
# PLAYER STATS
# =========================================================

def show_player_stats():
    st.markdown("## \U0001F40D PyCalc-Quest")
    streak = st.session_state.get("streak_count", 0)
    longest_streak = st.session_state.get("longest_streak", 0)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("\U0001F3C6 Rating", st.session_state.rating)
    with col2:
        st.metric("\U0001F396\uFE0F Rank", get_rank(st.session_state.rating))
    with col3:
        streak_label = f"{longest_streak} best" if longest_streak > streak else None
        st.metric("\U0001F525 Streak", f"{streak}d", delta=streak_label, delta_color="off")
    st.caption(f"\u2B50 {st.session_state.xp} XP earned")

    earned = len(st.session_state.get("achievements", []))
    total_badges = len(ACHIEVEMENTS)
    st.caption(f"\U0001F3C5 {earned}/{total_badges} achievements")


# =========================================================
# LESSONS
# =========================================================

LESSONS = {
    "Sequence": [
        ("What is Sequence?", """
**Sequence** is the simplest of the three building blocks of programming
(the other two are *Selection* and *Repetition*, which you'll meet in the
other topics). It just means one thing:

> Python runs your instructions **one line at a time, from top to bottom**,
> in the exact order you wrote them.

Nothing happens "at the same time," and nothing runs out of order unless
you tell Python to jump around (which is exactly what Selection and
Repetition let you do later).

```python
print("Hello")
print("Welcome")
print("Python")
```

Line 1 runs first and prints `Hello`. Only once it's completely finished
does line 2 run and print `Welcome`. Then line 3 runs last.

**Why this matters:** if you get the *order* of your lines wrong, your
program can crash or give the wrong answer - even if every individual
line is written correctly. For example, this will crash:

```python
print(favorite_number)
favorite_number = 7
```

Python hasn't created `favorite_number` yet when line 1 runs, so it has
no idea what to print. The fix is simply to swap the order:

```python
favorite_number = 7
print(favorite_number)
```

Keep this in mind for every challenge in this app: **a program that uses
the right ingredients in the wrong order is still wrong.**
"""),
        ("Variables", """
A **variable** is a labeled box that stores a piece of information so you
can use it later. You create one by picking a name and using `=` to store
a value in it.

```python
name = "Alex"
age = 18
```

Here, `name` is a box holding the text `"Alex"`, and `age` is a box
holding the number `18`. Whenever you type `name` later in your code,
Python replaces it with whatever is currently stored inside it.

**Two kinds of values you'll see a lot:**
- **Strings** - text, always wrapped in quotes: `"Alex"`, `"Hello!"`
- **Integers** - whole numbers, no quotes: `18`, `5`, `-3`

**Variables can change.** Assigning a new value to an existing variable
simply overwrites what was there before:

```python
score = 10
score = 20
print(score)   # prints 20 - the old value 10 is gone
```

**Naming rules (beginner-friendly version):** variable names can use
letters, numbers, and underscores, but can't start with a number and
can't contain spaces. `high_score` is fine. `2ndPlace` and `high score`
are not.
"""),
        ("Input and Output", """
So far our programs have only used values we typed directly into the
code. To make a program *interactive*, Python gives us two key tools:

- `print()` - **output**: displays something on the screen.
- `input()` - **input**: pauses the program and waits for the user to
  type something, then hands that text back to you.

```python
name = input("Enter your name: ")
print("Hello", name)
```

What happens, in order:
1. Python shows the message `"Enter your name: "` and waits.
2. The user types something, e.g. `Maria`, and presses Enter.
3. Python stores `"Maria"` inside the variable `name`.
4. `print("Hello", name)` runs, showing `Hello Maria`.

**Important beginner trap:** `input()` *always* gives you back text
(a string) - even if the user types a number! If you need to do math
with what the user typed, you must convert it first using `int()`:

```python
age = input("Enter your age: ")        # age is the TEXT "18"
age = int(input("Enter your age: "))   # age is the NUMBER 18
```

The second version lets you do `age + 1` without errors. The first one
would crash if you tried, because you can't add a number to text.
"""),
        ("Doing Calculations", """
Python can do arithmetic using the same symbols you already know, plus
one new one:

| Symbol | Meaning        | Example  | Result |
|--------|----------------|----------|--------|
| `+`    | addition       | `5 + 2`  | `7`    |
| `-`    | subtraction    | `5 - 2`  | `3`    |
| `*`    | multiplication | `5 * 2`  | `10`   |
| `/`    | division       | `5 / 2`  | `2.5`  |

You'll usually store the result of a calculation in a new variable so you
can use it again later, instead of just calculating and throwing it away:

```python
a = 10
b = 5
total = a + b

print(total)
```

Notice the **sequence** at work here: `total` is only calculated *after*
both `a` and `b` already exist. If `total = a + b` were the very first
line, Python wouldn't know what `a` and `b` are yet, and the program
would crash.

You can also combine several steps into one longer, still-sequential
program - this is exactly the kind of program you'll be asked to build
in the challenges ahead:

```python
price = 20
quantity = 3
tax = 5

final_price = price * quantity + tax
print("Total:", final_price)
```

Read it top to bottom: define the numbers first, calculate with them
second, then print the answer last. That order is not a style choice -
it's required, because each line depends on the one(s) above it.
"""),
    ],

    "Selection": [
        ("What is Selection?", """
Every program you've written so far runs *every single line*, every
single time. **Selection** statements change that - they let your program
make decisions and choose *which* lines to run, based on a condition.

The most important selection keyword is `if`. It checks whether something
is `True` or `False`, and only runs the indented code underneath it when
the condition is `True`.

```python
age = 18

if age >= 18:
    print("Adult")
```

Read this as: *"if `age` is greater than or equal to 18, then print
Adult."* Since `age` is `18`, the condition is `True`, so the print
statement runs.

**The colon `:` and the indentation are not optional.** Every line that
should run "inside" the `if` must be indented (usually 4 spaces), and the
`if` line itself must end with a colon. This tells Python exactly which
lines belong to the decision and which don't.

**Comparison operators** are how you build conditions:

| Operator | Meaning               |
|----------|-----------------------|
| `==`     | equal to              |
| `!=`     | not equal to          |
| `>`      | greater than          |
| `<`      | less than             |
| `>=`     | greater than or equal |
| `<=`     | less than or equal    |

Beginner trap: `=` **assigns** a value (`age = 18`), while `==`
**compares** two values (`age == 18`). Mixing them up is one of the most
common beginner errors in all of programming.
"""),
        ("if / else", """
`if` on its own only handles the "true" case. To also handle the
opposite case, add `else`:

```python
age = 15

if age >= 18:
    print("Adult")
else:
    print("Minor")
```

Python checks the condition exactly once. If it's `True`, it runs the
`if` block and **skips** the `else` block entirely. If it's `False`, it
skips the `if` block and runs the `else` block instead. Only ever one of
the two blocks runs - never both, never neither.

This is genuinely useful because most real decisions have two sides:
pass/fail, in stock/out of stock, adult/minor, and so on.
"""),
        ("elif - more than two choices", """
Real decisions often have more than two outcomes. Trying to write that
with only `if`/`else` gets awkward fast - so Python gives us `elif`
("else if") to chain extra conditions together:

```python
temperature = 35

if temperature >= 30:
    print("Hot")
elif temperature >= 15:
    print("Warm")
else:
    print("Cold")
```

Python checks the conditions **in order, top to bottom**, and runs the
*first* one that's `True` - then it stops checking the rest, even if a
later condition would also have been `True`. With `temperature = 35`:
- Is it `>= 30`? Yes - prints `Hot` and stops. It never even looks at
  the `elif` or `else` below.

You can chain as many `elif`s as you like between one `if` and one final
`else`. This is exactly how grading systems, temperature scales, and
game difficulty tiers are usually built in real code.
"""),
        ("Combining conditions: and / or", """
Sometimes one comparison isn't specific enough. Python's logical
operators let you combine multiple conditions into a single check:

- `and` - **both** sides must be `True` for the whole thing to be `True`.
- `or` - **at least one** side must be `True` for the whole thing to be
  `True`.

```python
age = 16

if age >= 13 and age <= 19:
    print("Teenager")
else:
    print("Not a teenager")
```

Here, `age >= 13 and age <= 19` is only `True` when *both* parts are
true. Since `16` satisfies both, it prints `Teenager`. If `age` were `25`,
the second part (`age <= 19`) would be `False`, making the whole
condition `False` - so it would print `Not a teenager` instead.

`or` works the opposite way - only one side needs to be true:

```python
day = "Saturday"

if day == "Saturday" or day == "Sunday":
    print("Weekend!")
```

This prints `Weekend!` if `day` is *either* `"Saturday"` **or**
`"Sunday"` - it doesn't need to be both (which would be impossible
anyway, since a variable can only hold one value at a time).
"""),
        ("Putting it together", """
Real programs usually combine everything from this topic: `input()` to
get information, `elif` chains to classify it, and `print()` to report
the result. Here's a small grading program that uses all of it:

```python
score = int(input("Enter your score: "))

if score >= 90:
    print("Grade: A")
elif score >= 75:
    print("Grade: B")
elif score >= 50:
    print("Grade: C")
else:
    print("Grade: F")
```

Walk through the logic with `score = 82`:
1. Is `score >= 90`? `82 >= 90` is `False` - skip.
2. Is `score >= 75`? `82 >= 75` is `True` - print `Grade: B` and stop.

Notice that the *order* of the conditions matters here too, just like in
Sequence. If you checked `score >= 50` first, a score of `95` would
incorrectly get caught by that check and print `Grade: C` instead of
`Grade: A` - because Python stops at the first `True` condition it finds.
That's why elif chains are almost always written from the highest
threshold down to the lowest.
"""),
    ],

    "Repetition": [
        ("What is Repetition?", """
So far, every extra line of output has meant an extra line of code - if
you wanted to print 100 numbers, you'd need 100 `print()` lines. **Loops**
solve this: they let you repeat the same instructions many times without
retyping them.

Python has two main kinds of loops:
- **`for` loop** - repeats a *known* number of times (or once per item in
  a collection).
- **`while` loop** - repeats for as long as a condition stays `True`
  (useful when you don't know the exact number of repeats in advance).

You'll meet both in this topic, starting with `for`.
"""),
        ("The for Loop and range()", """
A `for` loop, combined with the built-in `range()` function, repeats code
a specific number of times:

```python
for i in range(5):
    print(i)
```

This prints `0`, `1`, `2`, `3`, `4` - five numbers total. Two important
details:
- `range(5)` produces the numbers `0` up to (but **not including**) `5`.
  It starts counting at `0` by default.
- `i` is a normal variable - it's created fresh by the loop and updated
  automatically on every repeat. You can name it anything, but `i` is a
  common convention for "the current loop count."

`range()` is flexible - you can control the start, stop, and step size:

```python
range(5)         # 0, 1, 2, 3, 4          (stop only)
range(1, 6)      # 1, 2, 3, 4, 5          (start, stop)
range(0, 10, 2)  # 0, 2, 4, 6, 8          (start, stop, step)
```

The last example counts by 2s. `range(start, stop, step)` keeps adding
`step` to the current number, starting at `start`, and stops **before**
reaching `stop`.
"""),
        ("Accumulator pattern: totaling with a loop", """
One of the most useful loop patterns is the **accumulator**: a variable
that starts at `0` and slowly builds up a total as the loop runs.

```python
total = 0

for i in range(1, 6):
    total = total + i

print(total)   # 15  (1 + 2 + 3 + 4 + 5)
```

Trace through it step by step:

| i | total = total + i | total afterwards |
|---|--------------------|-------------------|
| 1 | 0 + 1              | 1                 |
| 2 | 1 + 2              | 3                 |
| 3 | 3 + 3              | 6                 |
| 4 | 6 + 4              | 10                |
| 5 | 10 + 5             | 15                |

Two things must be true for this pattern to work, in this exact order:
1. `total` must be created **before** the loop starts (usually at `0`).
2. Every repeat updates `total` using its *own current value* -
   `total = total + i` means "take what total already is, add `i`, and
   store that back into total."

Forgetting step 1 (no `total = 0` before the loop) would crash the
program, since `total` wouldn't exist yet the first time the loop tries
to use it.
"""),
        ("The while Loop", """
A `for` loop is great when you know exactly how many times to repeat. A
**`while`** loop repeats for as long as a condition stays `True` -
perfect for when you're counting *down to* something, or don't know the
exact number of repeats ahead of time.

```python
count = 5

while count > 0:
    print(count)
    count = count - 1

print("Liftoff!")
```

This counts down `5, 4, 3, 2, 1`, then prints `Liftoff!`. Walk through
why it eventually stops:
1. Python checks `count > 0`. If `True`, it runs the indented block.
2. It prints `count`, then does `count = count - 1`.
3. It jumps back to step 1 and checks again.
4. Once `count` reaches `0`, `count > 0` is `False`, so the loop ends and
   execution continues with the line *after* the loop (`print("Liftoff!")`).

**The most common `while`-loop bug:** forgetting to update the variable
inside the loop (here, `count = count - 1`). Without that line, `count`
would stay `5` forever, `count > 0` would never become `False`, and your
program would loop forever - this is called an **infinite loop**.
"""),
        ("Putting it together", """
Loops become really powerful once you combine them with `input()` and
the accumulator pattern from earlier in this topic:

```python
n = int(input("Sum up to what number? "))
total = 0

for i in range(1, n + 1):
    total = total + i

print("Sum is:", total)
```

Notice `range(1, n + 1)` - since `range()`'s stop value is never
included, we need `n + 1` so that `n` itself actually gets counted. If
the user enters `10`, this loop adds up every whole number from `1` to
`10` and prints `55`.

This is the same accumulator pattern from before, just with the number
of repeats now coming from the *user* instead of being hard-coded. This
combination - input to configure a loop, then an accumulator to total
the results - is exactly the pattern the challenges ahead will ask you
to build.
"""),
    ],
}


# =========================================================
# CHALLENGES
# =========================================================

CHALLENGES = {

    "Sequence": {
        1: {
            "type": "drag",
            "question": "Arrange the three lines into a program that stores a name, prints a greeting using that name, and finally prints a goodbye message. A variable must exist before any line that uses it.",
            "blocks": ['print("Hello,", name)', 'name = "Alex"', 'print("Goodbye!")'],
            "answer": ['name = "Alex"', 'print("Hello,", name)', 'print("Goodbye!")'],
            "hints": [
                "Which line *creates* the `name` variable? Python has to run that before any line that uses `name`.",
                "The block that creates `name` goes first. The goodbye message doesn't depend on `name` at all, so it makes sense as the very last line, after the greeting.",
            ],
        },
        2: {
            "type": "drag",
            "question": "Arrange the code into a program that creates two numbers, adds them into a total, and prints the total. `a` and `b` can be created in either order, but both must exist before `total` is calculated, and `total` must exist before it's printed.",
            "blocks": ["total = a + b", "a = 10", "print(total)", "b = 5"],
            # both orderings of the independent assignments are valid
            "answer": [
                ["a = 10", "b = 5", "total = a + b", "print(total)"],
                ["b = 5", "a = 10", "total = a + b", "print(total)"],
            ],
            "hints": [
                "`total = a + b` needs both `a` and `b` to already exist, so it can't be the first line.",
                "Once both numbers exist, only one line can calculate the total — and printing only makes sense once that total has actually been worked out.",
            ],
        },
        3: {
            "type": "drag",
            "question": "Arrange the code into a program that asks the user for their name, greets them by name, and then prints a welcome message. The variable storing the name must be created before it's used.",
            "blocks": ['print("Hello,", name)', 'name = input("Enter your name: ")', 'print("Welcome!")'],
            "answer": ['name = input("Enter your name: ")', 'print("Hello,", name)', 'print("Welcome!")'],
            "hints": [
                "`input()` is how the program asks the user something — that has to happen before you can greet them by name.",
                "Once the name is collected, the greeting can happen. The general welcome message doesn't depend on anything, so it fits naturally as the closing line.",
            ],
        },
        4: {
            "type": "drag",
            "question": "Arrange the code into a program that first announces it's calculating the area, then sets the rectangle's length and width (either order), then computes and prints the area. `area` needs both `length` and `width` to exist first, and `print(area)` needs `area` to exist first.",
            "blocks": ["area = length * width", "print(area)", "length = 10", "width = 5", 'print("Calculating area...")'],
            # the announcement doesn't depend on any variable, so it comes first;
            # length/width are independent of each other and can go in either order
            "answer": [
                ['print("Calculating area...")', "length = 10", "width = 5", "area = length * width", "print(area)"],
                ['print("Calculating area...")', "width = 5", "length = 10", "area = length * width", "print(area)"],
            ],
            "hints": [
                "The announcement message doesn't depend on any variable, so it's safe to print it first.",
                "`length` and `width` can be created in any order right after the announcement, but the multiplication needs both of them done first, and the final print has to be the very last line.",
            ],
        },
        5: {
            "type": "drag",
            "question": "Arrange the code into a program that asks for a name and age, greets the user by name, works out their age next year, prints that, and finishes with a friendly message. Both `input()` lines must run before their values are used, and `next_age` needs `age` to exist first.",
            "blocks": [
                'name = input("Name: ")', 'age = int(input("Age: "))', 'print("Hello", name)',
                "next_age = age + 1", 'print("Next year:", next_age)', 'print("Have a great day!")'
            ],
            "answer": [
                'name = input("Name: ")', 'age = int(input("Age: "))', 'print("Hello", name)',
                "next_age = age + 1", 'print("Next year:", next_age)', 'print("Have a great day!")'
            ],
            "hints": [
                "Both `input()` lines should come first — nothing later can run without them.",
                "Greet the user once you have their name. The next-year calculation needs `age` first, and it must happen before you print it. The friendly send-off doesn't depend on anything, so it fits best at the very end.",
            ],
        },
        6: {
            "type": "missing",
            "question": "This program stores a name and prints a welcome message. Type the missing line that prints the value of `name` itself, before the program says goodbye.",
            "lines": ['name = "Alex"', 'print("Welcome!")', None, 'print("Enjoy Python!")'],
            "missing_answers": ['print(name)'],
            "hints": [
                "You already have a variable called `name` — you just need to display it.",
                "Think about the one function that shows a value on screen, and the one variable you have that holds what you want to show.",
            ],
        },
        7: {
            "type": "missing",
            "question": "This program stores two numbers, a and b. Type the missing line that adds them together into a variable called `result`, which the next line then prints.",
            "lines": ["a = 20", "b = 10", None, 'print("Result:", result)', 'print("Done!")'],
            "missing_answers": ["result = a + b"],
            "hints": [
                "The variable used later is called `result` — what calculation stores a value there?",
                "You need an assignment that adds the two existing numbers together and saves the answer under the exact variable name used in the print line below.",
            ],
        },
        8: {
            "type": "missing",
            "question": "This program stores a name and welcomes the user. Fill in the two missing lines: the first creates a variable `score` and assign it to a value, and the second calculates `total` by adding 10 to `score` — which the last line then prints.",
            "lines": ['name = "Alex"', None, 'print("Welcome,", name)', None, 'print("Your total score is:", total)'],
            "missing_answers": ["re:score = -?\\d+", "re:total = score \\+ 10"],
            "hints": [
                "The first blank should create a new variable called `score`. The second blank should use it to calculate `total`.",
                "Pick any whole number for `score` in the first blank. In the second blank, add 10 to `score` and store the result in `total`, since that's the name the final print line expects.",
            ],
        },
        9: {
            "type": "missing",
            "question": "This program asks for a name and already has a `price`. It needs a `quantity` and a `tax` amount that is assigned to a whole number before it can work out `final_price = price * quantity + tax`. Fill in the three missing lines: create `quantity`, create `tax`, and print Total: final_price before thanking the user.",
            "lines": [
                'name = input("Enter your name: ")', None, 'price = 20', None,
                'final_price = price * quantity + tax', None, 'print("Thank you", name)'
            ],
            "missing_answers": ["re:quantity = -?\\d+", "re:tax = -?\\d+", 'print("Total:", final_price)'],
            "hints": [
                "`final_price` needs both `quantity` and `tax` to already exist — those are two of your three blanks.",
                "Two blanks just need to create `quantity` and `tax` with any whole number. The third blank prints `final_price` alongside a \"Total:\" label, after it's been calculated.",
            ],
        },
        10: {
            "type": "type",
            "question": "Type a complete program that asks for the user's name and age, works out their age next year, and prints a greeting followed by that next-year age.",
            "answer": (
                'name = input("Enter your name: ")\n'
                'age = int(input("Enter your age: "))\n'
                'next_age = age + 1\n'
                'print\(".+", name\)\n'
                'print\(".+", next_age\)'
            ),
            "test_inputs": [["Alex", "20"], ["Sam", "5"], ["Zoe", "0"], ["Jordan", "99"]],
            "hints": [
                "You'll need two `input()` lines (name, then age converted with `int()`), then a calculation, then two `print()` lines.",
                "After collecting the name and age, work out next year's age by adding 1. Then print a greeting using the name, followed by a message reporting the next-year age.",
            ],
        },
    },

    "Selection": {
        1: {
            "type": "drag",
            "question": "Arrange the code into a program that stores an age and prints \"Adult\" if that age is 18 or older. The variable must exist before the `if` checks it, and the indented line only runs when the condition is true.",
            "blocks": ['    print("Adult")', "age = 18", "if age >= 18:"],
            "answer": ["age = 18", "if age >= 18:", '    print("Adult")'],
            "hints": [
                "`age = 18` has to come before anything that checks `age`.",
                "After the variable, the `if` line has to come before the line it controls — and that controlled line needs to stay indented directly underneath it.",
            ],
        },
        2: {
            "type": "drag",
            "question": "Arrange the code into a program that prints \"Adult\" if the age is 18 or older, and \"Minor\" otherwise, using `if` / `else`.",
            "blocks": ["else:", '    print("Minor")', "age = 15", "if age >= 18:", '    print("Adult")'],
            "answer": ["age = 15", "if age >= 18:", '    print("Adult")', "else:", '    print("Minor")'],
            "hints": [
                "Set up `age` first, then the `if` line and its indented body, then `else:` and its own indented body.",
                "Each indented print has to stay directly under the condition line it belongs to — the `if` block first, then the `else` block right after it.",
            ],
        },
        3: {
            "type": "drag",
            "question": "Arrange the code into a program that classifies a temperature as \"Hot\" (30+), \"Warm\" (15-29), or \"Cold\" (below 15), using `if` / `elif` / `else`.",
            "blocks": [
                'elif temperature >= 15:', '    print("Warm")', "temperature = 20",
                "if temperature >= 30:", '    print("Hot")', "else:", '    print("Cold")'
            ],
            "answer": [
                "temperature = 20", "if temperature >= 30:", '    print("Hot")',
                'elif temperature >= 15:', '    print("Warm")', "else:", '    print("Cold")'
            ],
            "hints": [
                "Conditions must be checked from the highest threshold down to the lowest, or a hot temperature could get caught by a lower check first.",
                "After setting the temperature, the chain runs `if`, then `elif`, then `else`, from the highest number check down to the catch-all — each with its print directly indented underneath it.",
            ],
        },
        4: {
            "type": "drag",
            "question": "Arrange the code into a program that prints \"Teenager\" if the age is between 13 and 19 (inclusive), and \"Not a teenager\" otherwise. You'll need `and` to combine both parts of the condition.",
            "blocks": ['    print("Teenager")', "if age >= 13 and age <= 19:", "age = 16", "else:", '    print("Not a teenager")'],
            "answer": ["age = 16", "if age >= 13 and age <= 19:", '    print("Teenager")', "else:", '    print("Not a teenager")'],
            "hints": [
                "Both `age >= 13` and `age <= 19` must be true at once — that's a job for `and`.",
                "Set the age first. The combined condition and its indented result come next, then the `else` case and its own indented result last.",
            ],
        },
        5: {
            "type": "drag",
            "question": "Arrange the code into a program that asks for a score and prints a letter grade: \"A\" for 90+, \"B\" for 75-89, and \"F\" below that, checking from the highest threshold down to the lowest with an `if` / `elif` / `else` chain.",
            "blocks": [
                'score = int(input("Enter your score: "))', "if score >= 90:", '    print("Grade: A")',
                "elif score >= 75:", '    print("Grade: B")', "else:", '    print("Grade: F")'
            ],
            "answer": [
                'score = int(input("Enter your score: "))', "if score >= 90:", '    print("Grade: A")',
                "elif score >= 75:", '    print("Grade: B")', "else:", '    print("Grade: F")'
            ],
            "hints": [
                "`input()` has to run first, before anything checks the score.",
                "After asking for the score, check the highest grade boundary first, then the next one down, ending with the catch-all case — each grade's print stays directly under its own condition.",
            ],
        },
        6: {
            "type": "missing",
            "question": "This program should print \"Pass\" if the score is 50 or higher, and \"Fail\" otherwise. Fill in the missing `if` condition.",
            "lines": ["score = 75", None, '    print("Pass")', "else:", '    print("Fail")'],
            "missing_answers": ["if score >= 50:"],
            "hints": [
                "The blank needs to be an `if` line ending in a colon, matching up with the `else:` below it.",
                "The condition should compare `score` against the passing mark mentioned in the question, using \"greater than or equal to\".",
            ],
        },
        7: {
            "type": "missing",
            "question": "This program should print \"Positive\" if the number is greater than 0, and \"Negative or zero\" otherwise. Fill in the missing `if` line and the missing `else:` line.",
            "lines": ["number = -5", None, '    print("Positive")', None, '    print("Negative or zero")'],
            "missing_answers": ["if number > 0:", "else:"],
            "hints": [
                "The first blank needs a condition; the second blank pairs with it as the opposite case.",
                "The first blank checks whether `number` is greater than zero. The second blank is simply the keyword that handles every other case.",
            ],
        },
        8: {
            "type": "missing",
            "question": "This program grades a score as \"A\" (90+), \"B\" (75-89), or \"C\" (below that). Fill in the missing `elif` condition and the missing `else:` line.",
            "lines": [
                "score = 82", "if score >= 90:", '    print("Grade: A")', None,
                '    print("Grade: B")', None, '    print("Grade: C")'
            ],
            "missing_answers": ["elif score >= 75:", "else:"],
            "hints": [
                "The first blank continues checking after the `if` fails — that's what `elif` is for.",
                "The first blank checks the boundary for a \"B\" grade using `elif`. The second blank is the catch-all keyword for whatever's left.",
            ],
        },
        9: {
            "type": "missing",
            "question": "This program should print \"Valid\" if the number is between 1 and 100 (inclusive), and \"Invalid\" otherwise. Fill in the missing compound condition using `and`.",
            "lines": ["number = 42", None, '    print("Valid")', "else:", '    print("Invalid")'],
            "missing_answers": ["if number >= 1 and number <= 100:"],
            "hints": [
                "You need both `number >= 1` and `number <= 100` to be true at the same time.",
                "Combine a \"greater than or equal to 1\" check and a \"less than or equal to 100\" check into one condition using `and`.",
            ],
        },
        10: {
            "type": "type",
            "question": "Type a complete program that asks for the user's age and prints \"Child\" if under 13, \"Teenager\" if under 20, or \"Adult\" otherwise.",
            "answer": (
                'age = int(input("Enter your age: "))\n'
                'if age < 13:\n'
                '    print("Child")\n'
                'elif age < 20:\n'
                '    print("Teenager")\n'
                'else:\n'
                '    print("Adult")'
            ),
            "test_inputs": [["5"], ["12"], ["13"], ["19"], ["20"], ["45"]],
            "hints": [
                "You'll need one `input()` line and an `if` / `elif` / `else` chain checked from the lowest age boundary up.",
                "Convert the input to a whole number first. Then check the youngest boundary, then the next one up with `elif`, and let `else` catch everyone older.",
            ],
        },
    },

    "Repetition": {
        1: {
            "type": "drag",
            "question": "Arrange the code into a program that prints \"Start\", then prints the numbers 0 to 4 using a `for` loop.",
            "blocks": ["for i in range(5):", 'print("Start")', "    print(i)"],
            "answer": ['print("Start")', "for i in range(5):", "    print(i)"],
            "hints": [
                "`range(5)` counts from 0 up to (but not including) 5 — that's 5 numbers total.",
                "The header print doesn't depend on the loop at all, so it belongs before it. Whatever prints each number has to stay indented inside the loop.",
            ],
        },
        2: {
            "type": "drag",
            "question": "Arrange the code into a program that adds up the numbers 1 to 5 using a loop, and prints the total.",
            "blocks": ["    total = total + i", "total = 0", "print(total)", "for i in range(1, 6):"],
            "answer": ["total = 0", "for i in range(1, 6):", "    total = total + i", "print(total)"],
            "hints": [
                "`total` must be created and set to `0` before the loop starts, or the loop has nothing to add to.",
                "The line that updates `total` has to stay indented inside the loop, and the final print only makes sense once the loop has completely finished running.",
            ],
        },
        3: {
            "type": "drag",
            "question": "Arrange the code into a countdown program: start at 5, print each number down to 1 using a `while` loop, then print \"Liftoff!\" once the countdown ends.",
            "blocks": ['    count = count - 1', "while count > 0:", "count = 5", '    print(count)', 'print("Liftoff!")'],
            "answer": ["count = 5", "while count > 0:", '    print(count)', '    count = count - 1', 'print("Liftoff!")'],
            "hints": [
                "Don't forget to decrease `count` inside the loop, or it will never stop (an infinite loop).",
                "Both indented lines belong inside the loop, with the print happening before the decrease each time. The liftoff message only makes sense after the loop has ended.",
            ],
        },
        4: {
            "type": "drag",
            "question": "Arrange the code into a program that prints a header, then prints the even numbers from 0 to 8 using `range()`'s step argument.",
            "blocks": ["for i in range(0, 10, 2):", "    print(i)", 'print("Even numbers:")'],
            "answer": ['print("Even numbers:")', "for i in range(0, 10, 2):", "    print(i)"],
            "hints": [
                "`range(0, 10, 2)` counts by 2s, starting at 0 and stopping before 10.",
                "The header print doesn't depend on the loop at all, so it belongs before it. Whatever prints each number has to stay indented inside the loop.",
            ],
        },
        5: {
            "type": "drag",
            "question": "Arrange the code into a program that prints a header, then prints the 5-times multiplication table (5x1 through 5x10) using a `for` loop. The header and `number = 5` don't depend on each other, so either can come first — but both must come before the loop.",
            "blocks": [
                "number = 5", 'print("Multiplication table:")', "for i in range(1, 11):",
                '    print(number, "x", i, "=", number * i)'
            ],
            "answer": [
                [
                    "number = 5", 'print("Multiplication table:")', "for i in range(1, 11):",
                    '    print(number, "x", i, "=", number * i)'
                ],
                [
                    'print("Multiplication table:")', "number = 5", "for i in range(1, 11):",
                    '    print(number, "x", i, "=", number * i)'
                ],
            ],
            "hints": [
                "The loop line needs `number` to already exist, but the header print doesn't depend on anything.",
                "The loop needs to run 10 times, covering the multipliers 1 through 10 — think about what stop value gets you exactly that range.",
            ],
        },
        6: {
            "type": "missing",
            "question": "This program should add up the numbers 0 to 9 using a loop. Fill in the missing `for` line.",
            "lines": ["total = 0", None, "    total = total + i", "print(total)"],
            "missing_answers": ["for i in range(10):"],
            "hints": [
                "You need a `for` loop with `range()` covering 0 up to (not including) 10.",
                "A single number passed to `range()` counts from 0 up to (but not including) that number — what number gets you 0 through 9?",
            ],
        },
        7: {
            "type": "missing",
            "question": "This program should count up to 5 using a loop, then report that the loop finished and print the final count. Fill in the missing `for` line and the missing final print line.",
            "lines": ["count = 0", None, "    count = count + 1", 'print("Loop finished")', None],
            "missing_answers": ["for i in range(5):", 'print("Final count:", count)'],
            "hints": [
                "The loop needs to run exactly 5 times — that's `range(5)`.",
                "The second blank should print a label like \"Final count:\" together with the current value of `count`, after the loop is completely done.",
            ],
        },
        8: {
            "type": "missing",
            "question": "This program should print the numbers 0 to 4 using a `while` loop. Fill in the missing loop condition and the missing line that updates `count` (without it, the loop would never end).",
            "lines": ["count = 0", None, "    print(count)", None],
            "missing_answers": ["while count < 5:", "    count = count + 1"],
            "hints": [
                "The loop should keep going only while `count` is less than 5.",
                "Without an update inside the loop, `count` would never change — the second blank needs to increase `count` by 1 each time round.",
            ],
        },
        9: {
            "type": "missing",
            "question": "This program asks the user for a number, then should add up every whole number from 1 up to and including that number. Fill in the missing `for` line (remember `range()`'s stop value is never included) and the missing line that prints the result.",
            "lines": [
                'n = int(input("Sum up to what number? "))', "total = 0", None,
                "    total = total + i", None
            ],
            "missing_answers": ["for i in range(1, n + 1):", 'print("Sum is:", total)'],
            "hints": [
                "To include `n` itself, the loop needs to stop at `n + 1`, not `n`.",
                "The final blank should print a label like \"Sum is:\" together with the value of `total`, once the loop has finished adding everything up.",
            ],
        },
        10: {
            "type": "type",
            "question": "Type a complete program that adds up the numbers 1 to 10 using a loop, and prints the total as \"Sum is: <total>\".",
            "answer": (
                'total = 0\n'
                'for i in range(1, 11):\n'
                '    total = total + i\n'
                'print("Sum is:", total)'
            ),
            "test_inputs": [[]],
            "hints": [
                "You'll need an accumulator variable starting at 0, a `for` loop over `range(1, 11)`, and a print at the end.",
                "Inside the loop, add the loop variable to your running total each time round. Once the loop finishes, print the total alongside a \"Sum is:\" label.",
            ],
        },
    },

    # The secret boss node. One level, but it deliberately leans on all
    # three circuits at once: a starting value (Sequence), a loop over the
    # numbers (Repetition), and a check made on every one of them
    # (Selection) - so beating it really does mean the player can combine
    # everything, not just recall one topic in isolation.
    "Boss": {
        1: {
            "type": "drag",
            "question": (
                "This is it, Coder \u2014 the Core Breach. Arrange the code into a program "
                "that adds up only the EVEN numbers from 1 to 5 into a running total, "
                "printing each ODD number as it's skipped, then prints the final total "
                "once the loop finishes. It leans on everything you've learned: a "
                "starting value (Sequence), a loop over the numbers (Repetition), and a "
                "check made on every single one of them (Selection)."
            ),
            "blocks": [
                'print("Total:", total)',
                '        print("Odd:", num)',
                'total = 0',
                '    else:',
                '        total = total + num',
                'for num in range(1, 6):',
                '    if num % 2 == 0:',
            ],
            "answer": [
                'total = 0',
                'for num in range(1, 6):',
                '    if num % 2 == 0:',
                '        total = total + num',
                '    else:',
                '        print("Odd:", num)',
                'print("Total:", total)',
            ],
            "hints": [
                "Start with the total at 0 (Sequence) before anything can add to it. Then the `for` loop (Repetition) has to wrap the `if`/`else` check (Selection) that runs on every number.",
                "Indentation shows what belongs to what: the `if`/`else` lines sit one level inside the `for` loop, and each branch's action sits one level deeper than its own `if`/`else` line. The final print only makes sense after the loop has finished, so it comes last, back at the outer level.",
            ],
        },

        # Second boss stage - a "running best" pattern (start with a
        # baseline, loop over every item, replace the baseline whenever a
        # better one shows up). Same three circuits as stage 1, different
        # shape, and a notch harder since two blanks now have to work
        # together correctly instead of one drag-and-drop rearrangement.
        2: {
            "type": "missing",
            "question": (
                "Stage 2 of the Core Breach. This program finds the highest number in a "
                "list. Fill in the two missing lines: the first sets a starting point "
                "before the loop runs (Sequence), and the second is the check "
                "(Selection) made on every number (Repetition) that decides whether it "
                "beats the current highest."
            ),
            "lines": [
                "numbers = [4, 9, 2, 7, 5]",
                None,
                "for num in numbers:",
                None,
                "        highest = num",
                'print("Highest:", highest)',
            ],
            "missing_answers": ["highest = numbers[0]", "if num > highest:"],
            "hints": [
                "The first blank needs a starting guess for the highest number, before the loop has looked at anything - the first item in the list is the obvious choice.",
                "The second blank is the condition that decides when the current number beats the current highest. Get that comparison right and `highest = num` right underneath it takes care of the rest.",
            ],
        },

        # Final boss stage - the true capstone. No scaffolding at all now:
        # the player has to independently reach for a loop (Repetition)
        # wrapping a multi-branch check (Selection) that runs correctly on
        # every value in a range set up up front (Sequence).
        3: {
            "type": "type",
            "question": (
                "Final stage. Type a complete program that loops through the numbers 1 "
                "to 15 (inclusive) and, for each one, prints \"FizzBuzz\" if it's "
                "divisible by both 3 and 5, \"Fizz\" if divisible by 3 only, \"Buzz\" if "
                "divisible by 5 only, and otherwise just the number itself. Beat this "
                "and the Grid is fully stabilized."
            ),
            "answer": (
                'for i in range(1, 16):\n'
                '    if i % 3 == 0 and i % 5 == 0:\n'
                '        print("FizzBuzz")\n'
                '    elif i % 3 == 0:\n'
                '        print("Fizz")\n'
                '    elif i % 5 == 0:\n'
                '        print("Buzz")\n'
                '    else:\n'
                '        print(i)'
            ),
            "test_inputs": [[]],
            "hints": [
                "One `for` loop over `range(1, 16)`, with an `if`/`elif`/`elif`/`else` chain inside it.",
                "Check the strictest condition first - divisible by both 3 and 5 - before falling back to divisible by 3 alone, then 5 alone, then printing the plain number in the `else`.",
            ],
        },
    },
}


def is_boss_unlocked():
    """True once every level in every real circuit (Sequence, Selection,
    Repetition) has been stabilized - that's what reveals the secret 4th
    sector on the Home page."""
    return all(
        len(st.session_state.completed_levels.get(topic, [])) >= len(CHALLENGES[topic])
        for topic in TOPICS
    )


# =========================================================
# STREAKS & ACHIEVEMENTS
# ---------------------------------------------------------
# Both are derived from state that's already tracked (completed_levels,
# per-level performance flags, login dates) and persisted for real accounts
# alongside xp/rating/completed_levels. Guests still see them live-update
# during their session, they just don't carry over (same as everything
# else guests do).
# =========================================================

ACHIEVEMENTS = {
    "first_stabilize": {"emoji": "\U0001F527", "title": "First Stabilize", "desc": "Complete your very first node."},
    "perfect_run": {"emoji": "\U0001F4AF", "title": "Flawless Circuit", "desc": "Complete a node without losing a single heart."},
    "speed_demon": {"emoji": "\u26A1", "title": "Speed Demon", "desc": "Complete a node in under 10 seconds."},
    "sequence_master": {"emoji": "\U0001F9E9", "title": "Order Circuit Cleared", "desc": "Stabilize every node in Sector 01: Sequence."},
    "selection_master": {"emoji": "\U0001F500", "title": "Fork Node Cleared", "desc": "Stabilize every node in Sector 02: Selection."},
    "repetition_master": {"emoji": "\U0001F501", "title": "Loop Core Cleared", "desc": "Stabilize every node in Sector 03: Repetition."},
    "grid_savior": {"emoji": "\U0001F3C6", "title": "Grid Savior", "desc": "Fully stabilize all 3 main circuits and unlock the Core Breach."},
    "core_breach": {"emoji": "\U0001F451", "title": "Core Breach", "desc": "Defeat all 3 stages of the secret 4th sector."},
    "streak_3": {"emoji": "\U0001F525", "title": "3-Day Streak", "desc": "Play PyCalc-Quest 3 days in a row."},
    "streak_7": {"emoji": "\U0001F31F", "title": "7-Day Streak", "desc": "Play PyCalc-Quest 7 days in a row."},
}


def compute_unlocked_achievements():
    """Pure function of current session state -> the set of achievement ids
    that SHOULD be unlocked right now. check_and_unlock_achievements() diffs
    this against what's already recorded to find what's newly earned."""
    unlocked = set()
    cl = st.session_state.completed_levels

    if any(len(v) > 0 for v in cl.values()):
        unlocked.add("first_stabilize")
    if st.session_state.get("had_perfect_run"):
        unlocked.add("perfect_run")
    if st.session_state.get("had_speed_run"):
        unlocked.add("speed_demon")
    if len(cl.get("Sequence", [])) >= len(CHALLENGES["Sequence"]):
        unlocked.add("sequence_master")
    if len(cl.get("Selection", [])) >= len(CHALLENGES["Selection"]):
        unlocked.add("selection_master")
    if len(cl.get("Repetition", [])) >= len(CHALLENGES["Repetition"]):
        unlocked.add("repetition_master")
    if is_boss_unlocked():
        unlocked.add("grid_savior")
    if len(cl.get(BOSS_TOPIC, [])) >= len(CHALLENGES[BOSS_TOPIC]):
        unlocked.add("core_breach")
    if st.session_state.get("streak_count", 0) >= 3:
        unlocked.add("streak_3")
    if st.session_state.get("streak_count", 0) >= 7:
        unlocked.add("streak_7")
    return unlocked


def check_and_unlock_achievements():
    """Unlocks any newly-earned achievements, returns the list of ids that
    were newly unlocked this call (empty if nothing changed)."""
    unlocked_now = compute_unlocked_achievements()
    already = set(st.session_state.achievements)
    newly = [a for a in unlocked_now if a not in already]
    if newly:
        st.session_state.achievements.extend(newly)
    return newly


def update_daily_streak():
    """Bumps the login streak at most once per calendar day. Safe to call
    on every rerun - if last_play_date is already today, it's a no-op, so
    it doesn't matter how many times a single day's session reruns.
    Guests get this too (tracked in session state only, same as everything
    else guests do) - it just never reaches persist_progress()'s disk write,
    since that's already a no-op without a saved account."""
    today = date.today().isoformat()
    last = st.session_state.get("last_play_date")
    if last == today:
        return
    if last:
        try:
            gap = (date.today() - date.fromisoformat(last)).days
        except ValueError:
            gap = None
        st.session_state.streak_count = st.session_state.streak_count + 1 if gap == 1 else 1
    else:
        st.session_state.streak_count = 1
    st.session_state.longest_streak = max(
        st.session_state.get("longest_streak", 0), st.session_state.streak_count
    )
    st.session_state.last_play_date = today
    check_and_unlock_achievements()
    persist_progress()


# =========================================================
# START LEVEL
# =========================================================

def start_level(level):
    st.session_state.level = level
    st.session_state.max_health = get_max_health(level)
    st.session_state.health = st.session_state.max_health
    st.session_state.challenge_finished = False
    st.session_state.level_won = False
    st.session_state.last_event = None
    st.session_state.last_event_info = {}
    st.session_state.attempt_id = 0
    st.session_state.level_start_time = time.time()

    # Clear any typed/dragged answer left over from a previous attempt at this
    # level so "Retry Level" actually starts blank instead of pre-filling the
    # previous (wrong) answer. Matched by substring (not just prefix) since
    # widget keys now also carry an attempt id in the middle, e.g.
    # "missing_Sequence_6_2_0" for topic=Sequence, level=6, attempt=2, blank=0.
    topic = st.session_state.topic
    needle = f"_{topic}_{level}_"
    stale_starts = (f"missing_{topic}_{level}_", f"whole_code_{topic}_{level}_", f"drag_{topic}_{level}_")
    for key in list(st.session_state.keys()):
        if key.startswith(stale_starts) or needle in key:
            del st.session_state[key]

    challenge = CHALLENGES[st.session_state.topic][level]

    if challenge["type"] == "drag":
        blocks = challenge["blocks"].copy()
        answers = challenge["answer"]
        accepted = answers if (answers and isinstance(answers[0], list)) else [answers]
        for _ in range(10):
            random.shuffle(blocks)
            if blocks not in accepted:
                break
        st.session_state.shuffled_blocks = blocks


# =========================================================
# COMPLETE / FAIL LEVEL
# (these only update state + rerun; all rendering of results happens
#  at the top of the challenge page so it reflects the NEW state)
# =========================================================

def complete_level():
    level = st.session_state.level
    topic = st.session_state.topic
    hearts_left = st.session_state.health

    elapsed = time.time() - (st.session_state.level_start_time or time.time())
    time_bonus = get_time_bonus(level, elapsed)

    rating_gain = get_win_rating(level, hearts_left)
    xp_gain = 100 + (level * 10) + time_bonus

    st.session_state.rating += rating_gain
    st.session_state.xp += xp_gain

    if level not in st.session_state.completed_levels[topic]:
        st.session_state.completed_levels[topic].append(level)

    if hearts_left == st.session_state.max_health:
        st.session_state.had_perfect_run = True
    if elapsed < 10:
        st.session_state.had_speed_run = True

    st.session_state.challenge_finished = True
    st.session_state.level_won = True
    st.session_state.last_event = "correct"
    st.session_state.last_event_info = {
        "hearts_left": hearts_left,
        "rating_gain": rating_gain,
        "xp_gain": xp_gain,
        "elapsed": elapsed,
        "time_bonus": time_bonus,
        "newly_unlocked": check_and_unlock_achievements(),
    }
    persist_progress()
    st.rerun()


def wrong_answer(detail=None):
    """detail: an optional specific, non-answer-revealing reason the attempt
    failed (e.g. a real Python error, which test case mismatched, how many
    drag blocks were already in the right spot) - shown alongside the
    generic "wrong answer" message so a miss is more useful than a dead end."""
    st.session_state.health -= 1
    # A fresh attempt id forces every widget on the challenge page (the
    # Check Answer button, text inputs, and the drag-and-drop component) to
    # get a brand-new Streamlit widget identity next render. Without this,
    # some widgets - especially the third-party drag-and-drop component -
    # can keep replaying their very first stored value forever, which is
    # what caused hearts to only ever drop on the first wrong answer.
    st.session_state.attempt_id += 1

    if st.session_state.health <= 0:
        level = st.session_state.level
        rating_loss = get_loss_rating(level)
        st.session_state.rating = max(0, st.session_state.rating - rating_loss)
        st.session_state.challenge_finished = True
        st.session_state.last_event = "gameover"
        st.session_state.last_event_info = {"rating_loss": rating_loss, "detail": detail}
        persist_progress()
    else:
        st.session_state.last_event = "wrong"
        st.session_state.last_event_info = {"tries_left": st.session_state.health, "detail": detail}
    st.rerun()


def render_last_event():
    """Renders feedback + triggers sound/animation for whatever just happened,
    then clears the flag so it doesn\'t replay on unrelated reruns."""
    event = st.session_state.last_event
    info = st.session_state.last_event_info

    if event == "correct":
        st.markdown('<div class="glow-feedback">', unsafe_allow_html=True)
        st.success("\U0001F389 Correct! Level Complete!")
        show_confetti()
        render_mascot(mascot_line("correct"))
        st.markdown(
            f"""
            ### \U0001F3C6 Results

            \u2764\uFE0F Hearts remaining: **{info['hearts_left']}/{st.session_state.max_health}**

            \u23F1\uFE0F Time taken: **{info['elapsed']:.1f}s** (speed bonus: **+{info['time_bonus']} XP**)

            \U0001F3C6 Rating gained: **+{info['rating_gain']}**

            \u2B50 XP gained: **+{info['xp_gain']}**

            \U0001F3C6 Overall Rating: **{st.session_state.rating}**

            \U0001F396\uFE0F Rank: **{get_rank(st.session_state.rating)}**
            """
        )
        st.markdown("</div>", unsafe_allow_html=True)
        if st.session_state.sfx_on:
            play_sound("success")

        for aid in info.get("newly_unlocked", []):
            badge = ACHIEVEMENTS.get(aid)
            if not badge:
                continue
            st.markdown(
                f'<div class="achievement-unlock-toast">'
                f'\U0001F3C5 Achievement unlocked: <b>{badge["emoji"]} {badge["title"]}</b>'
                f'<br><span style="color:#a9b7c6; font-size:0.85rem;">{badge["desc"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    elif event == "wrong":
        st.markdown('<div class="shake-feedback">', unsafe_allow_html=True)
        st.error("\u274C Wrong answer!")
        render_mascot(mascot_line("wrong"))
        if info.get("detail"):
            st.info(f"\U0001F50D {info['detail']}")
        st.warning(f"You lost 1 \u2764\uFE0F. {info['tries_left']} tries remaining.")
        st.markdown("</div>", unsafe_allow_html=True)
        if st.session_state.sfx_on:
            play_sound("pop")

    elif event == "gameover":
        st.markdown('<div class="shake-feedback">', unsafe_allow_html=True)
        st.error("\U0001F494 You ran out of hearts!")
        render_mascot(mascot_line("gameover"))
        if info.get("detail"):
            st.info(f"\U0001F50D {info['detail']}")
        st.markdown(
            f"""
            ### Game Over

            \U0001F3C6 Rating lost: **-{info['rating_loss']}**

            \U0001F3C6 Overall Rating: **{st.session_state.rating}**

            \U0001F396\uFE0F Rank: **{get_rank(st.session_state.rating)}**
            """
        )
        st.markdown("</div>", unsafe_allow_html=True)
        if st.session_state.sfx_on:
            play_sound("gameover")

    st.session_state.last_event = None
    st.session_state.last_event_info = {}


# =========================================================
# AUTH PAGE (login / sign up / guest)
# =========================================================

def render_auth_page():
    st.title("\U0001F40D PyCalc-Quest")
    if st.session_state.is_guest and (st.session_state.xp or st.session_state.rating != GUEST_STARTING_RATING):
        st.write(
            f"You're **{st.session_state.rating} rating / {st.session_state.xp} XP** in as a guest. "
            "Sign up below to keep it permanently \u2014 or just head back in and keep playing."
        )
    else:
        st.write("Learn Python through lessons, challenges and progression!")
    st.divider()

    # st.tabs() always opens on its first tab and can't be switched
    # programmatically, so buttons elsewhere that promise to send a guest
    # straight to "Sign Up" (after their first win, or from the sidebar)
    # would land them back on "Log In" instead. A plain toggle driven by
    # session state lets those buttons actually open the right view.
    col_login, col_signup = st.columns(2)
    with col_login:
        if st.button(
            "\U0001F511 Log In",
            key="auth_view_login_btn",
            type="primary" if st.session_state.auth_view == "login" else "secondary",
            use_container_width=True,
        ):
            st.session_state.auth_view = "login"
            st.rerun()
    with col_signup:
        if st.button(
            "\U0001F4DD Sign Up",
            key="auth_view_signup_btn",
            type="primary" if st.session_state.auth_view == "signup" else "secondary",
            use_container_width=True,
        ):
            st.session_state.auth_view = "signup"
            st.rerun()
    st.divider()

    if st.session_state.auth_view == "login":
        st.subheader("Log In")
        login_user = st.text_input("Username", key="login_username")
        login_pass = st.text_input("Password", type="password", key="login_password")
        if st.button("Log In", key="login_btn"):
            username = login_user.strip()
            record = get_user(username)
            if record and verify_password(login_pass, record["salt"], record["password_hash"]):
                st.session_state.username = username
                st.session_state.is_guest = False
                load_user_progress(username)
                st.session_state.page = "home"
                st.rerun()
            else:
                st.error("Incorrect username or password.")

    else:
        st.subheader("Create an Account")
        new_user = st.text_input("Choose a username", key="signup_username")
        new_pass = st.text_input("Choose a password", type="password", key="signup_password")
        confirm_pass = st.text_input("Confirm password", type="password", key="signup_confirm")
        if st.button("Sign Up", key="signup_btn"):
            username = new_user.strip()
            if not username or not new_pass:
                st.error("Please fill in all fields.")
            elif get_user(username) is not None:
                st.error("That username is already taken.")
            elif new_pass != confirm_pass:
                st.error("Passwords do not match.")
            elif len(new_pass) < 4:
                st.error("Password must be at least 4 characters.")
            else:
                salt, pwd_hash = hash_password(new_pass)
                # Carry over whatever progress was made this session as a
                # guest, so "sign up to save your progress" is literally
                # true instead of resetting them back to zero.
                seed = None
                if st.session_state.is_guest:
                    seed = {
                        "xp": st.session_state.xp,
                        "rating": st.session_state.rating,
                        "completed_levels": st.session_state.completed_levels,
                        "achievements": st.session_state.achievements,
                        "streak_count": st.session_state.streak_count,
                        "longest_streak": st.session_state.longest_streak,
                        "last_play_date": st.session_state.last_play_date,
                        "had_perfect_run": st.session_state.had_perfect_run,
                        "had_speed_run": st.session_state.had_speed_run,
                    }
                create_user(username, salt, pwd_hash, seed=seed)
                st.session_state.username = username
                st.session_state.is_guest = False
                load_user_progress(username)
                st.session_state.page = "home"
                st.rerun()

    st.divider()
    if st.session_state.is_guest:
        if st.button("\u2B05\uFE0F Back to Game (keep playing as Guest)"):
            st.session_state.page = "home"
            st.rerun()
    else:
        st.caption("Just want to try it out?")
        if st.button("\U0001F464 Continue as Guest"):
            st.session_state.username = "Guest"
            st.session_state.is_guest = True
            st.session_state.xp = 0
            st.session_state.rating = GUEST_STARTING_RATING
            st.session_state.completed_levels = {t: [] for t in ALL_TOPICS}
            st.session_state.achievements = []
            st.session_state.streak_count = 0
            st.session_state.longest_streak = 0
            st.session_state.last_play_date = None
            st.session_state.had_perfect_run = False
            st.session_state.had_speed_run = False
            st.session_state.page = "home"
            st.rerun()
        st.caption("\u26A0\uFE0F Guest progress is **not saved** \u2014 it will be lost when you close or refresh the page.")


# =========================================================
# APP START
# =========================================================

init_state()
inject_theme()
update_daily_streak()

with st.sidebar:
    st.markdown("### \u2699\uFE0F Menu")

    if st.session_state.page != "auth":
        if st.session_state.is_guest:
            st.caption("\U0001F464 Playing as **Guest** \u2014 progress won't be saved")
            if st.button("\U0001F4DD Sign Up to Save Progress", type="primary"):
                st.session_state.auth_view = "signup"
                st.session_state.page = "auth"
                st.rerun()
        else:
            st.caption(f"\U0001F464 Logged in as **{st.session_state.username}**")

        if st.button("\U0001F3E0 Home"):
            st.session_state.page = "home"
            st.rerun()
        if st.button("\U0001F3C6 Leaderboard"):
            st.session_state.page = "leaderboard"
            st.rerun()
        if st.button("\U0001F3C5 Achievements"):
            st.session_state.page = "achievements"
            st.rerun()

        # Reset Progress is destructive and sat one accidental click away from
        # Home/Leaderboard, so it now needs a second, explicit confirmation
        # before anything actually gets wiped.
        if not st.session_state.confirm_reset:
            if st.button("\u267B\uFE0F Reset Progress"):
                st.session_state.confirm_reset = True
                st.rerun()
        else:
            st.warning("Erase all XP, rating and completed levels?")
            col_yes, col_no = st.columns(2)
            with col_yes:
                if st.button("\u2705 Yes, reset", type="primary"):
                    st.session_state.xp = 0
                    st.session_state.rating = (
                        GUEST_STARTING_RATING if st.session_state.is_guest else DEFAULT_RATING
                    )
                    st.session_state.completed_levels = {t: [] for t in ALL_TOPICS}
                    st.session_state.achievements = []
                    st.session_state.streak_count = 0
                    st.session_state.longest_streak = 0
                    st.session_state.last_play_date = None
                    st.session_state.had_perfect_run = False
                    st.session_state.had_speed_run = False
                    st.session_state.page = "home"
                    st.session_state.topic = None
                    st.session_state.lesson_page = 0
                    st.session_state.confirm_reset = False
                    persist_progress()
                    st.rerun()
            with col_no:
                if st.button("\u274C Cancel"):
                    st.session_state.confirm_reset = False
                    st.rerun()

        if not st.session_state.is_guest:
            if st.button("\U0001F6AA Logout"):
                persist_progress()
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                init_state()
                st.rerun()

        st.divider()
        st.markdown("### \U0001F50A Sound")
        new_sfx = st.checkbox("Sound effects", value=st.session_state.sfx_on)
        new_bgm = st.checkbox("Background music", value=st.session_state.bgm_on)
        if new_sfx != st.session_state.sfx_on or new_bgm != st.session_state.bgm_on:
            st.session_state.sfx_on = new_sfx
            st.session_state.bgm_on = new_bgm
            st.rerun()
        st.caption("Browsers block autoplay audio until you interact with the page \u2014 toggling these checkboxes counts as an interaction, so sound should start right after.")

if st.session_state.bgm_on and st.session_state.page != "auth":
    play_sound("bgm", loop=True)


# =========================================================
# AUTH
# =========================================================

if st.session_state.page == "auth":
    render_auth_page()


# =========================================================
# HOME
# =========================================================

elif st.session_state.page == "home":

    st.title("\U0001F40D PyCalc-Quest")

    total_completed = sum(len(v) for v in st.session_state.completed_levels.values())
    if total_completed == 0 and st.session_state.xp == 0:
        # Only greet brand-new players with the full hook - returning
        # players don't need the intro replayed every time they hit Home.
        render_mascot(mascot_line("welcome"))
    else:
        st.write("Learn Python through lessons, challenges and progression!")

    show_player_stats()
    st.divider()
    st.subheader("\U0001F4DA Choose a Sector")

    cols = st.columns(3)
    for col, topic in zip(cols, TOPICS):
        with col:
            world = WORLDS[topic]
            done = len(st.session_state.completed_levels[topic])
            total = len(CHALLENGES[topic])
            # Fixed-height card so all three sectors line up on the same row
            # no matter how long each tagline runs - without this, whichever
            # sector had the shortest text pushed its "Enter" button up
            # while the others sat lower, making the row look uneven/messy.
            with st.container(height=260, border=True):
                st.markdown(f"### {world['sector']}: {world['title']}")
                st.caption(f"*{topic}* \u2014 {done}/{total} nodes stabilized")
                st.caption(world["tagline"])
                if st.button(f"Enter {world['sector']}", key=f"study_{topic}", use_container_width=True):
                    st.session_state.topic = topic
                    st.session_state.lesson_page = 0
                    st.session_state.page = "lesson"
                    st.rerun()

    if is_boss_unlocked():
        st.markdown("<div style='height: 0.75rem'></div>", unsafe_allow_html=True)
        boss = WORLDS[BOSS_TOPIC]
        boss_stages_done = len(st.session_state.completed_levels.get(BOSS_TOPIC, []))
        boss_stages_total = len(CHALLENGES[BOSS_TOPIC])
        boss_done = boss_stages_done >= boss_stages_total
        st.markdown(
            f'<div class="boss-banner">'
            f'<div class="boss-tag">\u26A0\uFE0F {boss["sector"]} \u2014 UNLOCKED</div>'
            f'<div class="boss-title">{boss["title"]}{" \u2705" if boss_done else ""}</div>'
            f'<div class="boss-tagline">{boss["tagline"]}</div>'
            f'<div class="boss-tagline">{boss_stages_done}/{boss_stages_total} stages stabilized</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        boss_label = "\U0001F501 Re-enter the Core" if boss_stages_done > 0 else "\u2620\uFE0F Enter the Core Breach"
        if st.button(boss_label, key="enter_boss", type="primary", use_container_width=True):
            st.session_state.topic = BOSS_TOPIC
            st.session_state.page = "levels"
            st.rerun()
    else:
        total_topics_done = sum(
            1 for t in TOPICS if len(st.session_state.completed_levels[t]) >= len(CHALLENGES[t])
        )
        if total_topics_done > 0:
            st.caption(
                f"\U0001F512 A hidden 4th sector is sealed until all 3 circuits are fully "
                f"stabilized ({total_topics_done}/3 done)."
            )


# =========================================================
# LEADERBOARD
# =========================================================

elif st.session_state.page == "leaderboard":

    st.title("\U0001F3C6 Leaderboard")
    st.write("Top 10 players, ranked by overall rating (ties broken by XP).")

    if st.session_state.is_guest:
        st.info(
            "\U0001F464 You're playing as a **Guest**, so your progress isn't saved "
            "and won't show up here. Sign up to claim a spot on the board!"
        )

    board = get_leaderboard(top_n=10)

    if not board:
        st.write("No ranked players yet \u2014 sign up and be the first!")
    else:
        medals = {1: "\U0001F947", 2: "\U0001F948", 3: "\U0001F949"}
        you = None if st.session_state.is_guest else st.session_state.username
        for i, entry in enumerate(board, start=1):
            is_you = entry["username"] == you
            place = medals.get(i, f"#{i}")
            you_tag = "  \U0001F449 **(you)**" if is_you else ""
            css_class = "level-done" if is_you else "level-open"
            st.markdown(
                f'<div class="level-card {css_class}">'
                f'{place}&nbsp;&nbsp;<b>{entry["username"]}</b>{you_tag}'
                f'<br>\U0001F3C6 {entry["rating"]} rating &middot; '
                f'\u2B50 {entry["xp"]} XP &middot; {get_rank(entry["rating"])}'
                f'</div>',
                unsafe_allow_html=True,
            )

        # if the logged-in user isn't in the top 10, show them where they stand
        if you and you not in [e["username"] for e in board]:
            your_data = get_user(you)
            if your_data:
                all_users = get_all_users()
                all_entries = get_leaderboard(top_n=len(all_users))
                usernames_sorted = [e["username"] for e in all_entries]
                your_place = usernames_sorted.index(you) + 1
                st.divider()
                st.caption(f"Your rank: #{your_place}")
                st.markdown(
                    f'<div class="level-card level-locked">'
                    f'#{your_place}&nbsp;&nbsp;<b>{you}</b>  \U0001F449 **(you)**'
                    f'<br>\U0001F3C6 {your_data.get("rating", 1000)} rating &middot; '
                    f'\u2B50 {your_data.get("xp", 0)} XP &middot; '
                    f'{get_rank(your_data.get("rating", 1000))}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    st.divider()
    if st.button("\u2B05\uFE0F Back to Home", key="leaderboard_home"):
        st.session_state.page = "home"
        st.rerun()


# =========================================================
# ACHIEVEMENTS PAGE
# =========================================================

elif st.session_state.page == "achievements":

    st.title("\U0001F3C5 Achievements")
    earned = set(st.session_state.achievements)
    st.write(f"Unlocked **{len(earned)}/{len(ACHIEVEMENTS)}** badges.")

    if st.session_state.is_guest:
        st.info(
            "\U0001F464 You're playing as a **Guest**, so unlocked badges won't be "
            "saved between sessions. Sign up to keep them permanently!"
        )

    st.divider()
    for aid, badge in ACHIEVEMENTS.items():
        unlocked = aid in earned
        css_class = "achievement-badge" if unlocked else "achievement-badge locked"
        emoji = badge["emoji"] if unlocked else "\U0001F512"
        st.markdown(
            f'<div class="{css_class}">'
            f'<span class="a-title">{emoji} {badge["title"]}</span>'
            f'<span class="a-desc">{badge["desc"]}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.divider()
    if st.button("\u2B05\uFE0F Back to Home", key="achievements_home"):
        st.session_state.page = "home"
        st.rerun()


# =========================================================
# LESSON PAGE
# =========================================================

elif st.session_state.page == "lesson":

    topic = st.session_state.topic
    lessons = LESSONS[topic]
    lesson_index = st.session_state.lesson_page
    title, content = lessons[lesson_index]

    show_player_stats()
    st.divider()
    st.title(f"\U0001F4D6 {topic}")
    st.progress((lesson_index + 1) / len(lessons))
    st.header(title)
    st.markdown(content)
    st.divider()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if lesson_index > 0 and st.button("\u2B05\uFE0F Previous"):
            st.session_state.lesson_page -= 1
            st.rerun()

    with col2:
        if lesson_index < len(lessons) - 1:
            if st.button("Next \u27A1\uFE0F"):
                st.session_state.lesson_page += 1
                st.rerun()
        else:
            if st.button("\U0001F3AE Start Challenges"):
                st.session_state.page = "levels"
                st.rerun()

    with col3:
        if st.button("\u23ED\uFE0F Skip Lesson"):
            st.session_state.page = "levels"
            st.rerun()

    with col4:
        if st.button("\U0001F3E0 Home", key="lesson_home"):
            st.session_state.page = "home"
            st.rerun()


# =========================================================
# LEVEL SELECTION
# =========================================================

elif st.session_state.page == "levels":

    topic = st.session_state.topic
    topic_levels = CHALLENGES[topic]
    world = WORLDS[topic]

    show_player_stats()
    st.divider()
    st.title(f"\U0001F3AE {world['sector']}: {world['title']}")
    st.markdown(
        f'<div class="sector-banner">'
        f'<div class="sector-tag">{topic.upper()} \u2014 NODE MAP</div>'
        f'<div class="sector-tagline">{world["tagline"]}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    for level in sorted(topic_levels.keys()):
        unlocked = level == 1 or (level - 1) in st.session_state.completed_levels[topic]
        completed = level in st.session_state.completed_levels[topic]
        node_title = LEVEL_TITLES.get(topic, {}).get(level, f"Level {level}")

        # The level itself IS the play button - no separate "Play" button.
        # status_key drives both the button's CSS look (done/open/locked, see
        # inject_theme) and whether it's clickable at all.
        if completed:
            status_key = "done"
            label = f"\u2705  Node {level}: {node_title} \u2014 Stabilized  \u00b7  tap to replay"
        elif unlocked:
            status_key = "open"
            label = f"\U0001F513  Node {level}: {node_title} \u2014 Unlocked  \u00b7  tap to play"
        else:
            # Locked nodes stay unnamed - a little mystery about what's next
            # is part of what makes unlocking it feel earned.
            status_key = "locked"
            label = f"\U0001F512  Node {level} \u2014 Locked"

        clicked = st.button(
            label,
            key=f"level_{status_key}_{topic}_{level}",
            use_container_width=True,
            disabled=not unlocked,
        )
        if clicked and unlocked:
            start_level(level)
            st.session_state.page = "challenge"
            st.rerun()

    st.divider()
    if st.button("\u2B05\uFE0F Back to Sectors"):
        st.session_state.page = "home"
        st.rerun()


# =========================================================
# CHALLENGE PAGE
# =========================================================

elif st.session_state.page == "challenge":

    topic = st.session_state.topic
    level = st.session_state.level
    challenge = CHALLENGES[topic][level]

    show_player_stats()
    st.divider()
    node_title = LEVEL_TITLES.get(topic, {}).get(level, f"Level {level}")
    st.title(f"\U0001F3AE Node {level}: {node_title}")
    st.caption(f"{WORLDS[topic]['sector']}: {WORLDS[topic]['title']}")

    # feedback from the action that just happened (if any) renders first,
    # since it may reflect a health change that the hearts below must match
    if st.session_state.last_event:
        animate = "pop" if st.session_state.last_event in ("wrong", "gameover") else None
        render_last_event()
        show_hearts(animate=animate)
    else:
        show_hearts()

    st.markdown(
        f'<div style="text-align:center">Attempts remaining: '
        f'{st.session_state.health}/{st.session_state.max_health}</div>',
        unsafe_allow_html=True
    )
    if not st.session_state.challenge_finished and st.session_state.level_start_time:
        # A live, client-side clock: it ticks with the browser's own JS timer
        # (setInterval) instead of Streamlit's server-side rerun, so it counts
        # up every second on its own instead of staying frozen at 0s until the
        # player clicks/drags something.
        pool = get_time_bonus_pool(level)
        start_ms = int(st.session_state.level_start_time * 1000)
        components.html(
            f"""
            <style>
                html, body {{ margin:0; padding:0; background:transparent; }}
            </style>
            <div id="pcq-timer" style="
                text-align:center;
                font-family:'Courier New',monospace;
                color:#e6f7ff;
                opacity:0.9;
                padding:6px 0;
                background:#0a0e18;
                border:1px solid rgba(0,255,242,0.35);
                border-radius:8px;
                box-shadow:0 0 10px rgba(0,255,242,0.15);
            ">
                \u23F1\uFE0F <span id="pcq-elapsed">0</span>s elapsed &middot;
                speed bonus if you finish now:
                +<span id="pcq-bonus">{pool}</span> XP
            </div>
            <script>
                (function() {{
                    var start = {start_ms};
                    var pool = {pool};
                    var elapsedEl = document.getElementById("pcq-elapsed");
                    var bonusEl = document.getElementById("pcq-bonus");
                    function tick() {{
                        var elapsed = Math.floor((Date.now() - start) / 1000);
                        if (elapsed < 0) elapsed = 0;
                        var bonus = pool - elapsed;
                        if (bonus < 0) bonus = 0;
                        if (elapsedEl) elapsedEl.textContent = elapsed;
                        if (bonusEl) bonusEl.textContent = bonus;
                    }}
                    tick();
                    setInterval(tick, 1000);
                }})();
            </script>
            """,
            height=40,
        )
    st.divider()
    st.subheader(challenge["question"])

    # Hints unlock progressively: lose 1 heart, unlock hint 1; lose another,
    # unlock hint 2; and so on. Once all authored hints for this challenge
    # are unlocked, extra wrong answers just keep them all visible.
    hints = challenge.get("hints", [])
    if hints and not st.session_state.challenge_finished:
        hearts_lost = st.session_state.max_health - st.session_state.health
        unlocked = min(hearts_lost, len(hints))
        if unlocked > 0:
            with st.expander(f"\U0001F4A1 Hints ({unlocked}/{len(hints)} unlocked)", expanded=True):
                for i in range(unlocked):
                    st.markdown(f"**Hint {i + 1}:** {hints[i]}")
            if unlocked < len(hints):
                st.caption("\U0001F4A1 Miss another attempt to unlock the next hint.")
        else:
            st.caption("\U0001F4A1 Stuck? Getting an answer wrong unlocks a hint.")

    # attempt_id changes every time an answer is wrong, which forces every
    # widget below (button, text inputs, drag-and-drop) to be recreated with
    # a brand new key each attempt instead of reusing stale widget state.
    attempt = st.session_state.attempt_id
    widget_scope = f"{topic}_{level}_{attempt}"

    # ---------------- DRAG AND DROP ----------------
    if challenge["type"] == "drag":
        if not st.session_state.challenge_finished:
            sorted_blocks = sort_items(
                st.session_state.shuffled_blocks,
                direction="vertical",
                key=f"drag_{widget_scope}",
            )
            if st.button("\u2705 Check Answer", key=f"check_{widget_scope}"):
                if check_drag_answer(sorted_blocks, challenge["answer"]):
                    complete_level()
                else:
                    wrong_answer(drag_feedback(sorted_blocks, challenge["answer"]))
        else:
            st.info("This level has been completed.")

    # ---------------- MISSING LINES ----------------
    elif challenge["type"] == "missing":
        user_answers = []
        for i, line in enumerate(challenge["lines"]):
            if line is None:
                answer = st.text_input(
                    "\u270F\uFE0F Type the missing line:",
                    key=f"missing_{widget_scope}_{i}",
                )
                user_answers.append(answer)
            else:
                st.code(line)

        if not st.session_state.challenge_finished:
            if st.button("\u2705 Check Answer", key=f"check_{widget_scope}"):
                wrong_blanks = [
                    i + 1
                    for i, (user, expected) in enumerate(zip(user_answers, challenge["missing_answers"]))
                    if not check_missing_line(user, expected)
                ]
                if not wrong_blanks:
                    complete_level()
                else:
                    if len(wrong_blanks) == 1:
                        detail = f"Blank #{wrong_blanks[0]} doesn't look right yet."
                    else:
                        nums = ", ".join(f"#{n}" for n in wrong_blanks)
                        detail = f"Blanks {nums} don't look right yet."
                    wrong_answer(detail)

    # ---------------- TYPE WHOLE PROGRAM ----------------
    elif challenge["type"] == "type":
        st.write("\u2328\uFE0F Type the complete Python program.")
        user_code = st.text_area("Your code:", height=300, key=f"whole_code_{widget_scope}")

        if not st.session_state.challenge_finished:
            if st.button("\u2705 Check Code", key=f"check_{widget_scope}"):
                test_cases = challenge.get("test_inputs")
                if test_cases is not None:
                    # Run the student's program and the reference answer
                    # side by side and compare what they print, so any
                    # logically-correct program passes - not just one
                    # exact wording.
                    correct, detail = programs_behave_the_same(
                        user_code, challenge["answer"], test_cases
                    )
                else:
                    correct = normalize_code(user_code) == normalize_code(challenge["answer"])
                    detail = None if correct else "Your code doesn't match the expected program yet."
                if correct:
                    complete_level()
                else:
                    wrong_answer(detail)

    # ---------------- AFTER CHALLENGE ----------------
    if st.session_state.challenge_finished:
        st.divider()
        next_level = level + 1
        has_next_level = (
            st.session_state.level_won
            and next_level in CHALLENGES[topic]
        )

        if has_next_level:
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("\u27A1\uFE0F Next Level", type="primary"):
                    start_level(next_level)
                    st.session_state.page = "challenge"
                    st.rerun()
            with col2:
                if st.button("\U0001F504 Retry Level"):
                    start_level(level)
                    st.rerun()
            with col3:
                if st.button("\u2B05\uFE0F Node Map"):
                    st.session_state.page = "levels"
                    st.rerun()
        else:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("\U0001F504 Retry Level"):
                    start_level(level)
                    st.rerun()
            with col2:
                if st.button("\u2B05\uFE0F Node Map"):
                    st.session_state.page = "levels"
                    st.rerun()
    else:
        if st.button("\u2B05\uFE0F Back to Levels"):
            st.session_state.page = "levels"
            st.rerun()

import streamlit as st

st.set_page_config(page_title="PyCalc-Quest", page_icon="🐍", layout="wide")

if "mode" not in st.session_state:
    st.session_state.mode = "selection_page"
if "chosen_concept" not in st.session_state:
    st.session_state.chosen_concept = None
if "level" not in st.session_state:
    st.session_state.level = 1
if "score" not in st.session_state:
    st.session_state.score = 0
if "correct" not in st.session_state:
    st.session_state.correct = False
if "tries_left" not in st.session_state:
    st.session_state.tries_left = 3
if "show_wrong_alert" not in st.session_state:
    st.session_state.show_wrong_alert = False

# 📋 DYNAMIC DESIGN INJECTION: Turns the inner text area box red on errors
if st.session_state.show_wrong_alert and st.session_state.tries_left < 3 and not st.session_state.correct:
    st.markdown("""
    <style>
        div[data-baseweb="base-input"] {
            border: 2px solid #e74c3c !important;
            background-color: #fdf2f2 !important;
            border-radius: 8px !important;
        }
        textarea {
            background-color: #fdf2f2 !important;
            color: #c0392b !important;
        }
    </style>
    """, unsafe_allow_html=True)

quiz_data = {
    "Sequence (Jujukan)": {
        1: {"t": "Sequence Level 1", "i": "Calculate total cost for 5 journals at RM12 each.", "r": ["5", "12", "*"]},
        2: {"t": "Sequence Level 2", "i": "Calculate cake price: Base RM45 + Topping RM15.", "r": ["45", "15", "+"]},
        3: {"t": "Sequence Level 3", "i": "Calculate total for 35 liters at RM2.05 per liter.", "r": ["35", "2.05", "*"]},
        4: {"t": "Sequence Level 4", "i": "Calculate ride fare: Base RM28 - Promo RM5.", "r": ["28", "5", "-"]},
        5: {"t": "Sequence Level 5", "i": "Calculate 12% tax deduction on gross pay of RM3500.", "r": ["3500", "0.12", "*"]}
    },
    "Selection (Pilihan)": {
        1: {
            "t": "Level 1: Bookstore Tiers",
            "i": "A bookstore offers discounts based on book price thresholds:\n\n• **Price < RM50:** 5% (0.05) discount\n• **Price RM50 to RM100:** 10% (0.10) discount\n• **Price > RM100:** 20% (0.20) discount\n\n👉 **Task:** Calculate the total discount value for a book checking out at **RM75**.",
            "r": ["if", "elif", "75", "0.10"]
        },
        2: {
            "t": "Level 2: Electricity Usage Tiers",
            "i": "An electric utility company measures seasonal wattage metrics:\n\n• **Usage < 500 watts:** RM0.50 per watt\n• **Usage 500 to 1000 watts:** RM0.45 per watt\n• **Usage > 1000 watts:** RM0.40 per watt\n\n👉 **Task:** Calculate the total bill for a measured track of **1200 watts**.",
            "r": ["if", "elif", "1200", "0.40"]
        },
        3: {
            "t": "Level 3: Gym Contract Rates",
            "i": "A fitness club scales discounts according to entry tier lines:\n\n• **Premium membership:** 25% (0.25) discount\n• **Standard membership:** 15% (0.15) discount\n• **Basic membership:** 5% (0.05) discount\n\n👉 **Task:** Calculate the clean price deduction factor for a **'Premium'** sign-up.",
            "r": ["if", "elif", "Premium", "0.25"]
        },
        4: {
            "t": "Level 4: Resort Room Surcharges",
            "i": "A resort hotel evaluates occupancy processing taxes matching room rates:\n\n• **Rate > RM200:** 15% (0.15) tax\n• **Rate RM100 to RM200:** 10% (0.10) tax\n• **Rate <= RM100:** 5% (0.05) tax\n\n👉 **Task:** Compute the final room balance after tax for a flat invoice rate of **RM250**.",
            "r": ["if", "elif", "250", "0.15"]
        },
        5: {
            "t": "Level 5: Health Metrics Classifier",
            "i": "Process medical tags based on body mass targets:\n\n• **BMI < 18.5:** 'Underweight'\n• **BMI 18.5 to 24.9:** 'Normal weight'\n• **BMI 25.0 to 29.9:** 'Overweight'\n• **BMI >= 30.0:** 'Obesity'\n\n👉 **Task:** Formulate a logic path assessing an evaluation metric of **26.5**.",
            "r": ["if", "elif", "26.5", "Overweight"]
        },
        6: {
            "t": "Level 6: Input State Checker",
            "i": "Evaluate number polarity dynamically.\n\n👉 **Task:** Formulate a condition testing whether an intake logging variable is positive, negative, or zero using `num = -8`.",
            "r": ["if", "elif", "else", "-8"]
        },
        7: {
            "t": "Level 7: Outlet Wardrobe Specials",
            "i": "A clothing store updates discounts on checkout lines:\n\n• **Price > RM150:** 15% (0.15) discount\n• **Price <= RM150:** 5% (0.05) discount\n\n👉 **Task:** Calculate the savings value for an apparel product costing **RM180**.",
            "r": ["if", "else", "180", "0.15"]
        },
        8: {
            "t": "Level 8: Restaurant Set Tariffs",
            "i": "A food bistro assesses service taxes against ordered meals:\n\n• **Price > RM100:** 10% (0.10) tax\n• **Price <= RM100:** 5% (0.05) tax\n\n👉 **Task:** Calculate final payment details for a combo priced at **RM85**.",
            "r": ["if", "else", "85", "0.05"]
        },
        9: {
            "t": "Level 9: Cellular Account Audit",
            "i": "A telephone network updates monthly loyalty rebates matching balances:\n\n• **Usage < RM50:** No discount given (0%)\n• **Usage < RM100:** Get 5% (0.05) discount\n• **Usage RM100 and above:** Get 20% (0.20) discount\n\n👉 **Task:** Calculate the billing deduction statement for a usage account tracking **RM120**.",
            "r": ["if", "elif", "120", "0.20"]
        }
    },
    "Repetition (Gelung)": {
        1: {"t": "Loop Level 1", "i": "Print statement 4 times using a 'for' loop.", "r": ["for", "in", "range", "4"]},
        2: {"t": "Loop Level 2", "i": "Track flat savings of RM20/week over 6 weeks using 'for'.", "r": ["for", "in", "range", "20", "6"]},
        3: {"t": "Loop Level 3", "i": "Sum list items using a 'for' loop: 5, 12, 8, 15.", "r": ["for", "in", "5", "12", "8", "15"]},
        4: {"t": "Loop Level 4", "i": "Aggregate cargo dimensions list: 100, 200, 300.", "r": ["for", "in", "100", "200", "300"]},
        5: {"t": "Loop Level 5", "i": "Sum list [45, -5, 20, 30] while using 'if' to ignore numbers < 0.", "r": ["for", "if", "45", "-5", "20", "30"]}
    }
}

max_levels = 9 if st.session_state.chosen_concept == "Selection (Pilihan)" else 5

if st.session_state.mode == "selection_page":
    st.title("🐍 PyCalc-Quest: Dashboard Pintar")
    st.caption("Selamat Datang! Sila pilih kategori cabaran kod untuk mulakan pengembaraan.")
    st.divider()
    
    st.subheader("Pilih Jenis Tugasan / Kategori Cabaran:")
    concept = st.radio("Kategori Tersedia:", ["Sequence (Jujukan)", "Selection (Pilihan)", "Repetition (Gelung)"], index=1, horizontal=True)
    st.write("")
    if st.button("🚀 Sahkan & Teruskan ke Tutorial", type="primary", use_container_width=True):
        st.session_state.chosen_concept = concept
        st.session_state.mode = "tutorial_page"
        st.rerun()

elif st.session_state.mode == "tutorial_page":
    concept = st.session_state.chosen_concept
    st.title(f"📖 Panduan Pandu Arah: {concept}")
    st.divider()
    if concept == "Sequence (Jujukan)":
        st.info("### Sequence (Jujukan)\nKod berjalan baris demi baris dari atas ke bawah.")
    elif concept == "Selection (Pilihan)":
        st.info("### Selection (Pilihan)\nKenyataan bersyarat menggunakan `if`, `elif`, dan `else`.")
    elif concept == "Repetition (Gelung)":
        st.info("### Repetition (Gelung)\nPengulangan arahan menggunakan gelung `for`.")
    if st.button("🎮 Masuki Arena Cabaran (Mula Kuiz)", type="primary"):
        st.session_state.level = 1
        st.session_state.score = 0
        st.session_state.correct = False
        st.session_state.tries_left = 3
        st.session_state.show_wrong_alert = False
        st.session_state.mode = "quiz_page"
        st.rerun()

elif st.session_state.mode == "quiz_page":
    concept = st.session_state.chosen_concept
    lvl = st.session_state.level
    dataset = quiz_data[concept]
    st.title(f"🐍 PyCalc-Quest: {concept}")
    
    if lvl > max_levels:
        st.balloons()
        st.success(f"🎉 TAHNIAH! Anda menyelesaikan semua cabaran bagi {concept}! Skor Akhir: {st.session_state.score} XP")
        if st.button("🔄 Halaman Utama", type="primary"):
            st.session_state.mode = "selection_page"
            st.rerun()
    else:
        st.metric("Markah Semasa", f"{st.session_state.score} XP")
        st.progress(int(((lvl - 1) / max_levels) * 100) if lvl > 1 else 10, text=f"Soalan {lvl} daripada {max_levels}")
        st.divider()
        
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader(dataset[lvl]["t"])
            st.info(dataset[lvl]["i"])
            
            if st.session_state.correct:
                st.markdown("✅ **Status:** Tahap Berjaya Diselesaikan!")
            elif st.session_state.tries_left > 0:
                st.markdown(f"⏳ **Had Cubaan Berbaki:** `{st.session_state.tries_left}` pusingan")
            else:
                st.markdown("🚨 **Status:** Tiada cubaan bagi soalan ini!")
            
        with col_right:
            if st.session_state.show_wrong_alert and st.session_state.tries_left > 0 and not st.session_state.correct:
                st.error(f"⚠️ JAWAPAN SALAH! Cuba lagi. Anda hanya tinggal {st.session_state.tries_left} peluang sahaja!")
            elif st.session_state.tries_left == 0 and not st.session_state.correct:
                st.error("❌ HAD PERCUBAAN TAMAT! Sila klik butang Seterusnya untuk beralih ke soalan baru.")
                
            uc = st.text_area("Taip kod Python anda di sini:", value="# Tulis kod...\n", height=150, key=f"uc_{lvl}")
            col_btn1, col_btn2 = st.columns(2)
if st.button("🚀 Semak Jawapan", type="primary", use_container_width=True, disabled=is_locked):if all(x in uc for x in dataset[lvl]["r"]):st.success("🎉 TEPAT SEKALI! Sila klik Seterusnya.")st.session_state.show_wrong_alert = Falseif not st.session_state.correct:st.session_state.score += 100st.session_state.correct = Trueelse:st.session_state.tries_left -= 1st.session_state.show_wrong_alert = Truest.rerun()with col_btn2:if st.session_state.correct or st.session_state.tries_left <= 0:if st.button("➡️ Seterusnya", use_container_width=True):st.session_state.level += 1st.session_state.correct = Falsest.session_state.tries_left = 3st.session_state.show_wrong_alert = Falsest.rerun()
            
            with col_btn1:
                is_locked = st.session_state.correct or st.session_state.tries_left <= 0

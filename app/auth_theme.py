

"""Auth page theme: colorful CSS + SVG illustration for login/sign-up pages.

Zero dependencies — uses Streamlit native HTML/CSS/SVG.
"""

import html

import streamlit as st


AUTH_CSS = """
<style>
div[data-testid="stAppViewContainer"] > section.main {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 40%, #0d9488 100%);
}
div[data-testid="stAppViewContainer"] {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 40%, #0d9488 100%);
}
div[data-testid="stToolbar"] { display: none; }
header[data-testid="stHeader"] { background: transparent; }
footer { visibility: hidden; }
#MainMenu { visibility: hidden; }

.st-key-auth_card {
    background: rgba(255, 255, 255, 0.08);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 24px;
    padding: 3rem 2.5rem;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.4);
}

.auth-brand {
    font-size: 2.5rem;
    font-weight: 800;
    background: linear-gradient(135deg, #5eead4, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    text-align: center;
    margin-bottom: 0.5rem;
    letter-spacing: -0.02em;
}
.auth-tagline {
    color: #cbd5e1;
    text-align: center;
    font-size: 0.95rem;
    margin-bottom: 2.5rem;
    font-weight: 400;
}

/* Progress indicator */
.auth-progress {
    display: flex;
    justify-content: center;
    gap: 1rem;
    margin-bottom: 2rem;
    align-items: center;
}
.auth-progress-step {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    font-size: 0.85rem;
    font-weight: 600;
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
    color: #94a3b8;
    transition: all 0.3s ease;
}
.auth-progress-step.active {
    background: linear-gradient(135deg, #0d9488, #6366f1);
    border-color: #5eead4;
    color: white;
    transform: scale(1.1);
}
.auth-progress-step.done {
    background: rgba(94, 234, 212, 0.2);
    border-color: #5eead4;
    color: #5eead4;
}
.auth-progress-connector {
    width: 1.5rem;
    height: 2px;
    background: rgba(255, 255, 255, 0.1);
}
.auth-progress-connector.done {
    background: #5eead4;
}

/* Form fields */
.st-key-auth_card label {
    color: #e2e8f0 !important;
    font-weight: 500 !important;
    margin-bottom: 0.5rem !important;
    font-size: 0.95rem !important;
}

/* Inputs: style Streamlit's own field wrapper (styling the inner <input>
   as well draws a second, misaligned box) */
.st-key-auth_card [data-baseweb="input"],
.st-key-auth_card [data-baseweb="base-input"] {
    background: rgba(255, 255, 255, 0.06) !important;
    border-radius: 12px !important;
    transition: box-shadow 0.2s ease, background 0.2s ease !important;
}
.st-key-auth_card [data-baseweb="input"]:focus-within {
    background: rgba(255, 255, 255, 0.1) !important;
    box-shadow: 0 0 0 3px rgba(94, 234, 212, 0.25) !important;
}
.st-key-auth_card input { background: transparent !important; color: #f1f5f9 !important; }
.st-key-auth_card input::placeholder { color: #64748b !important; }

/* Form section headers */
.auth-form-section-title {
    color: #cbd5e1;
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

/* Button styling */
.auth-btn-primary {
    background: linear-gradient(135deg, #0d9488, #6366f1) !important;
    border: none !important;
    border-radius: 12px !important;
    color: white !important;
    font-weight: 600 !important;
    padding: 0.9rem 1.5rem !important;
    transition: all 0.3s ease !important;
    letter-spacing: 0.01em !important;
    font-size: 0.95rem !important;
}

.auth-btn-primary:hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 30px -5px rgba(13, 148, 136, 0.3) !important;
}

.auth-btn-secondary {
    background: rgba(255, 255, 255, 0.08) !important;
    border: 1px solid rgba(255, 255, 255, 0.2) !important;
    border-radius: 12px !important;
    color: #e2e8f0 !important;
    font-weight: 500 !important;
    padding: 0.85rem 1.5rem !important;
    transition: all 0.3s ease !important;
    font-size: 0.9rem !important;
}

.auth-btn-secondary:hover {
    background: rgba(255, 255, 255, 0.12) !important;
    border-color: rgba(255, 255, 255, 0.35) !important;
}

div[data-testid="stFormSubmitButton"] button {
    min-width: 100% !important;
}

/* Form submit buttons */
div[data-testid="stFormSubmitButton"] button {
    background: linear-gradient(135deg, #0d9488, #6366f1) !important;
    border: none !important;
    border-radius: 12px !important;
    color: white !important;
    font-weight: 600 !important;
    padding: 0.9rem 1.5rem !important;
    transition: all 0.3s ease !important;
    letter-spacing: 0.01em !important;
    font-size: 0.95rem !important;
    width: 100% !important;
}

div[data-testid="stFormSubmitButton"] button:hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 30px -5px rgba(13, 148, 136, 0.3) !important;
}

/* Regular buttons in forms */
.st-key-auth_card .stButton > button {
    background: rgba(255, 255, 255, 0.08) !important;
    border: 1px solid rgba(255, 255, 255, 0.2) !important;
    border-radius: 12px !important;
    color: #e2e8f0 !important;
    font-weight: 500 !important;
    padding: 0.75rem 1.25rem !important;
    transition: all 0.3s ease !important;
    font-size: 0.9rem !important;
}

.st-key-auth_card .stButton > button:hover {
    background: rgba(255, 255, 255, 0.12) !important;
    border-color: rgba(255, 255, 255, 0.35) !important;
}

/* Alerts and messages */
.st-key-auth_card div[data-testid="stAlert"] {
    border-radius: 12px !important;
    padding: 1rem !important;
}

.st-key-auth_card div[data-testid="stAlert"][kind="error"] {
    background: rgba(239, 68, 68, 0.15) !important;
    border: 1px solid rgba(239, 68, 68, 0.3) !important;
    color: #fca5a5 !important;
}

.st-key-auth_card div[data-testid="stAlert"][kind="success"] {
    background: rgba(34, 197, 94, 0.15) !important;
    border: 1px solid rgba(34, 197, 94, 0.3) !important;
    color: #86efac !important;
}

.st-key-auth_card div[data-testid="stAlert"][kind="info"] {
    background: rgba(59, 130, 246, 0.15) !important;
    border: 1px solid rgba(59, 130, 246, 0.3) !important;
    color: #93c5fd !important;
}

.st-key-auth_card div[data-testid="stAlert"][kind="warning"] {
    background: rgba(245, 158, 11, 0.15) !important;
    border: 1px solid rgba(245, 158, 11, 0.3) !important;
    color: #fcd34d !important;
}

/* Divider */
.st-key-auth_card hr {
    border-color: rgba(255, 255, 255, 0.1) !important;
    margin: 1.5rem 0 !important;
}

/* Helper text */
.auth-helper-text {
    color: #94a3b8;
    font-size: 0.85rem;
    margin-top: 0.5rem;
}

/* Link styling */
.st-key-auth_card a {
    color: #5eead4 !important;
    text-decoration: none;
    font-weight: 500;
}

.st-key-auth_card a:hover {
    text-decoration: underline;
    color: #a78bfa !important;
}

/* Illustration column */
.auth-illustration-col {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    padding: 2rem;
}

.auth-illustration {
    text-align: center;
}

.auth-illustration svg {
    max-width: 100%;
    height: auto;
    margin-bottom: 2rem;
}

.auth-illustration h2 {
    color: #e2e8f0;
    font-size: 1.5rem;
    font-weight: 700;
    margin: 1.5rem 0 1rem 0;
}

.auth-illustration p {
    color: #cbd5e1;
    font-size: 0.95rem;
    line-height: 1.6;
}

/* Illustration column */
.auth-illustration-col {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    padding: 2rem;
}

.auth-illustration {
    text-align: center;
}

.auth-illustration svg {
    max-width: 100%;
    height: auto;
    margin-bottom: 2rem;
}

.auth-illustration h2 {
    color: #e2e8f0;
    font-size: 1.5rem;
    font-weight: 700;
    margin: 1.5rem 0 1rem 0;
}

.auth-illustration p {
    color: #cbd5e1;
    font-size: 0.95rem;
    line-height: 1.6;
}

/* Landing page styles */
.landing-hero {
    text-align: center;
    padding: 4rem 2rem;
    background: linear-gradient(135deg, rgba(13, 148, 136, 0.1), rgba(99, 102, 241, 0.1));
    border-radius: 24px;
    margin-bottom: 3rem;
    border: 1px solid rgba(255, 255, 255, 0.1);
}

.landing-hero h1 {
    font-size: 3.5rem;
    font-weight: 900;
    background: linear-gradient(135deg, #5eead4, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 1rem;
    letter-spacing: -0.02em;
}

.landing-hero p {
    font-size: 1.25rem;
    color: #cbd5e1;
    margin-bottom: 0.5rem;
    line-height: 1.6;
}

.landing-hero .subtext {
    color: #94a3b8;
    font-size: 1rem;
    margin-top: 2rem;
}

.landing-cta-buttons {
    display: flex;
    gap: 1.5rem;
    justify-content: center;
    flex-wrap: wrap;
    margin-top: 2rem;
}

.landing-cta-btn {
    display: inline-block;
    padding: 1rem 2.5rem;
    border-radius: 14px;
    font-weight: 600;
    font-size: 1.05rem;
    text-decoration: none;
    transition: all 0.3s ease;
    border: 2px solid transparent;
}

.landing-cta-btn.primary {
    background: linear-gradient(135deg, #0d9488, #6366f1);
    color: white;
}

.landing-cta-btn.primary:hover {
    transform: translateY(-4px);
    box-shadow: 0 20px 40px -10px rgba(13, 148, 136, 0.4);
}

.landing-cta-btn.secondary {
    background: rgba(255, 255, 255, 0.08);
    border-color: rgba(255, 255, 255, 0.2);
    color: #e2e8f0;
}

.landing-cta-btn.secondary:hover {
    background: rgba(255, 255, 255, 0.12);
    border-color: rgba(255, 255, 255, 0.35);
}

/* Features grid */
.features-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 1.5rem;
    margin: 3rem 0;
}

/* Feature / testimonial cards use real st.container(border=True) blocks
   (not raw HTML divs) so the :material/icon: shortcode actually renders —
   Streamlit only substitutes icon shortcodes in its own native markdown/
   widget text, never inside custom HTML passed through unsafe_allow_html. */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: rgba(255, 255, 255, 0.08);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.15) !important;
    border-radius: 16px !important;
    transition: all 0.3s ease;
}

div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    background: rgba(255, 255, 255, 0.12);
    border-color: rgba(255, 255, 255, 0.25) !important;
    transform: translateY(-4px);
}

div[data-testid="stVerticalBlockBorderWrapper"] h3,
div[data-testid="stVerticalBlockBorderWrapper"] h4 {
    color: #e2e8f0;
}

div[data-testid="stVerticalBlockBorderWrapper"] p {
    color: #cbd5e1;
    line-height: 1.6;
}

.testimonial-quote em {
    color: #e2e8f0;
    font-size: 0.95rem;
    line-height: 1.6;
}

.testimonial-author {
    color: #cbd5e1;
    font-weight: 500;
    font-size: 0.9rem;
}

/* Stats section */
.stats-section {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 1rem;
    margin: 2rem 0;
    text-align: center;
}

.stat-box {
    padding: 1.5rem;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.1);
}

.stat-box .number {
    font-size: 2rem;
    font-weight: 800;
    background: linear-gradient(135deg, #5eead4, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.stat-box .label {
    color: #cbd5e1;
    font-size: 0.85rem;
    margin-top: 0.5rem;
}

/* Authenticated dashboard hero — compact variant of .landing-hero for
   pages where is_auth == true (shown above the chat/nav, not instead of it) */
.dashboard-hero {
    text-align: center;
    padding: 2rem 2rem;
    background: linear-gradient(135deg, rgba(13, 148, 136, 0.12), rgba(99, 102, 241, 0.12));
    border-radius: 20px;
    margin-bottom: 1.5rem;
    border: 1px solid rgba(255, 255, 255, 0.1);
}

.dashboard-hero h4 {
    font-size: 1.9rem;
    font-weight: 800;
    background: linear-gradient(135deg, #5eead4, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0 0 0.35rem 0 !important;
    letter-spacing: -0.01em;
}

.dashboard-hero [data-testid="stCaptionContainer"] {
    display: flex;
    justify-content: center;
}

.business-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    margin-top: 1rem;
    padding: 0.4rem 1rem;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.15);
    color: #e2e8f0;
    font-size: 0.9rem;
    font-weight: 500;
}

/* Responsive design */
@media (max-width: 768px) {
    .auth-illustration-col { display: none; }
    .st-key-auth_card {
        padding: 2rem 1.5rem;
    }
    .auth-brand {
        font-size: 2rem;
    }
    .landing-hero h1 {
        font-size: 2.5rem;
    }
    .landing-hero {
        padding: 3rem 1.5rem;
    }
    .landing-cta-buttons {
        flex-direction: column;
    }
}
/* ================= Motion: login / sign-up / landing =================
   Everything below is decoration; it is switched off for people whose
   system asks for reduced motion (see the media query at the end). */

/* Slowly shifting background with drifting light orbs */
div[data-testid="stAppViewContainer"] {
    background: linear-gradient(120deg, #0f172a, #1e3a5f, #0f766e, #312e81, #0f172a) !important;
    background-size: 300% 300% !important;
    animation: duka-bg-shift 24s ease-in-out infinite;
}
div[data-testid="stAppViewContainer"]::before,
div[data-testid="stAppViewContainer"]::after {
    content: "";
    position: fixed;
    width: 42vmax; height: 42vmax;
    border-radius: 50%;
    filter: blur(80px);
    opacity: 0.28;
    pointer-events: none;
    z-index: 0;
}
div[data-testid="stAppViewContainer"]::before {
    background: radial-gradient(circle, #5eead4 0%, transparent 65%);
    top: -12vmax; left: -10vmax;
    animation: duka-orb-a 26s ease-in-out infinite;
}
div[data-testid="stAppViewContainer"]::after {
    background: radial-gradient(circle, #a78bfa 0%, transparent 65%);
    bottom: -14vmax; right: -12vmax;
    animation: duka-orb-b 30s ease-in-out infinite;
}
section[data-testid="stMain"] { position: relative; z-index: 1; }

@keyframes duka-bg-shift { 0%, 100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
@keyframes duka-orb-a { 0%, 100% { transform: translate(0, 0) scale(1); } 50% { transform: translate(14vw, 10vh) scale(1.15); } }
@keyframes duka-orb-b { 0%, 100% { transform: translate(0, 0) scale(1.1); } 50% { transform: translate(-12vw, -8vh) scale(0.9); } }
@keyframes duka-rise { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }
@keyframes duka-slide-in { from { opacity: 0; transform: translateX(28px); } to { opacity: 1; transform: none; } }
@keyframes duka-float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-8px); } }
@keyframes duka-shimmer { 0% { background-position: 0% 50%; } 100% { background-position: 200% 50%; } }
@keyframes duka-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(94, 234, 212, 0.45); } 70% { box-shadow: 0 0 0 10px rgba(94, 234, 212, 0); } }
@keyframes duka-border-spin { to { --duka-angle: 360deg; } }
@property --duka-angle { syntax: "<angle>"; initial-value: 0deg; inherits: false; }

/* The card: glass, rises in on load, with a slowly turning light edge */
.st-key-auth_card {
    position: relative;
    animation: duka-rise 0.7s cubic-bezier(.2, .8, .2, 1) both;
    box-shadow: 0 30px 60px -20px rgba(2, 6, 23, 0.65), inset 0 1px 0 rgba(255, 255, 255, 0.08);
}
.st-key-auth_card::before {
    content: "";
    position: absolute; inset: -1px;
    border-radius: 24px;
    padding: 1px;
    background: conic-gradient(from var(--duka-angle), transparent 0deg, rgba(94, 234, 212, 0.75) 60deg,
                transparent 120deg, transparent 240deg, rgba(167, 139, 250, 0.7) 300deg, transparent 360deg);
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    -webkit-mask-composite: xor;
    mask-composite: exclude;
    animation: duka-border-spin 8s linear infinite;
    pointer-events: none;
}
/* Widgets inside the card appear one after another */
.st-key-auth_card > div > div { animation: duka-rise 0.6s cubic-bezier(.2, .8, .2, 1) both; }
.st-key-auth_card > div > div:nth-child(2) { animation-delay: .08s; }
.st-key-auth_card > div > div:nth-child(3) { animation-delay: .16s; }
.st-key-auth_card > div > div:nth-child(4) { animation-delay: .24s; }
.st-key-auth_card > div > div:nth-child(n+5) { animation-delay: .32s; }

/* Brand: floating logo, shimmering name */
.duka-logo-wrap svg { animation: duka-float 5s ease-in-out infinite; filter: drop-shadow(0 12px 24px rgba(13, 148, 136, 0.45)); }
.auth-brand {
    background: linear-gradient(90deg, #5eead4, #a78bfa, #f9a8d4, #5eead4) !important;
    background-size: 200% auto !important;
    -webkit-background-clip: text !important; background-clip: text !important;
    animation: duka-shimmer 6s linear infinite;
}
.auth-progress-step.active { animation: duka-pulse 2.2s ease-out infinite; }

/* Primary actions: a light sweep on hover */
.st-key-auth_card [data-testid="stFormSubmitButton"] button {
    background: linear-gradient(110deg, #0d9488 0%, #6366f1 50%, #0d9488 100%) !important;
    background-size: 200% auto !important;
    border: none !important; color: #fff !important; font-weight: 600 !important;
    transition: background-position .6s ease, transform .2s ease, box-shadow .2s ease !important;
}
.st-key-auth_card [data-testid="stFormSubmitButton"] button:hover {
    background-position: 100% 0 !important;
    transform: translateY(-2px);
    box-shadow: 0 14px 28px -10px rgba(99, 102, 241, 0.6);
}
.st-key-auth_card [data-testid="stForm"] { border-color: rgba(255, 255, 255, 0.12) !important; }

/* Illustration panel */
.st-key-auth_side { animation: duka-rise .8s .15s cubic-bezier(.2, .8, .2, 1) both; padding: 1rem 0.5rem; }
.duka-side { text-align: center; }
.duka-side .duka-art svg { max-width: 300px; width: 100%; height: auto; animation: duka-float 7s ease-in-out infinite; }
.duka-side h2 { color: #f1f5f9; font-size: 1.6rem; font-weight: 800; margin: .5rem 0 .4rem; letter-spacing: -0.01em; }
.duka-side .lede { color: #cbd5e1; font-size: .95rem; line-height: 1.6; margin: 0 auto 1.4rem; max-width: 30rem; }

/* Activity feed: what Duka Copilot does while you run the shop */
.duka-feed { display: flex; flex-direction: column; gap: .6rem; max-width: 26rem; margin: 0 auto 1.4rem; text-align: left; }
.duka-note {
    display: flex; gap: .75rem; align-items: center;
    background: rgba(15, 23, 42, 0.55); border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 14px; padding: .7rem .9rem;
    backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
    opacity: 0; animation: duka-slide-in .7s cubic-bezier(.2, .8, .2, 1) forwards;
}
.duka-note:nth-child(1) { animation-delay: .5s; }
.duka-note:nth-child(2) { animation-delay: 1.3s; }
.duka-note:nth-child(3) { animation-delay: 2.1s; }
.duka-note:nth-child(4) { animation-delay: 2.9s; }
.duka-note .dot { flex: 0 0 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; }
.duka-note .dot svg { width: 18px; height: 18px; }
.duka-note b { display: block; color: #f1f5f9; font-size: .9rem; font-weight: 600; }
.duka-note span { color: #94a3b8; font-size: .8rem; }
.duka-note .when { margin-left: auto; color: #64748b; font-size: .72rem; white-space: nowrap; }

/* Trust badges */
.duka-trust { display: flex; flex-wrap: wrap; gap: .5rem; justify-content: center; }
.duka-trust span {
    color: #e2e8f0; font-size: .78rem; padding: .35rem .75rem; border-radius: 999px;
    background: rgba(255, 255, 255, 0.07); border: 1px solid rgba(255, 255, 255, 0.14);
    opacity: 0; animation: duka-rise .6s forwards;
}
.duka-trust span:nth-child(1) { animation-delay: 3.4s; }
.duka-trust span:nth-child(2) { animation-delay: 3.6s; }
.duka-trust span:nth-child(3) { animation-delay: 3.8s; }

@media (prefers-reduced-motion: reduce) {
    div[data-testid="stAppViewContainer"], div[data-testid="stAppViewContainer"]::before,
    div[data-testid="stAppViewContainer"]::after, .st-key-auth_card, .st-key-auth_card::before,
    .st-key-auth_card > div > div, .duka-logo-wrap svg, .auth-brand, .auth-progress-step.active,
    .st-key-auth_side, .duka-side .duka-art svg, .duka-note, .duka-trust span {
        animation: none !important; opacity: 1 !important; transform: none !important;
    }
}
@media (max-width: 768px) { .st-key-auth_side { display: none; } }
</style>
"""


DUKA_LOGO_SVG = """
<svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect width="64" height="64" rx="16" fill="url(#g)"/>
  <path d="M20 38V26L32 16L44 26V38L32 48L20 38Z" fill="white" fill-opacity="0.95"/>
  <circle cx="32" cy="32" r="6" fill="url(#c)"/>
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="64" y2="64">
      <stop offset="0%" stop-color="#0d9488"/>
      <stop offset="100%" stop-color="#6366f1"/>
    </linearGradient>
    <linearGradient id="c" x1="26" y1="26" x2="38" y2="38">
      <stop offset="0%" stop-color="#5eead4"/>
      <stop offset="100%" stop-color="#a78bfa"/>
    </linearGradient>
  </defs>
</svg>
"""


SHOP_ILLUSTRATION = """
<svg width="280" height="240" viewBox="0 0 280 240" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="100" y="80" width="120" height="120" rx="8" fill="url(#bldg)" opacity="0.9"/>
  <rect x="100" y="80" width="120" height="20" rx="8" fill="url(#roof)"/>
  <rect x="145" y="150" width="30" height="50" rx="6" fill="white" opacity="0.25"/>
  <circle cx="170" cy="175" r="3" fill="white" opacity="0.6"/>
  <rect x="112" y="100" width="24" height="24" rx="4" fill="white" opacity="0.2"/>
  <rect x="144" y="100" width="24" height="24" rx="4" fill="white" opacity="0.2"/>
  <rect x="176" y="100" width="24" height="24" rx="4" fill="white" opacity="0.2"/>
  <rect x="112" y="134" width="24" height="24" rx="4" fill="white" opacity="0.2"/>
  <rect x="176" y="134" width="24" height="24" rx="4" fill="white" opacity="0.2"/>
  <path d="M95 76 L240 76 L225 86 L110 86 Z" fill="url(#awn)" opacity="0.85"/>
  <rect x="130" y="56" width="60" height="18" rx="6" fill="url(#sign)"/>
  <text x="160" y="69" text-anchor="middle" fill="white" font-size="10" font-weight="700">DUKA</text>
  <circle cx="240" cy="50" r="10" fill="url(#coin1)" opacity="0.9">
    <animateTransform attributeName="transform" type="translate" values="0,0; 0,-8; 0,0" dur="3s" repeatCount="indefinite"/>
  </circle>
  <circle cx="50" cy="70" r="8" fill="url(#coin2)" opacity="0.85">
    <animateTransform attributeName="transform" type="translate" values="0,0; 0,-6; 0,0" dur="2.5s" repeatCount="indefinite"/>
  </circle>
  <circle cx="200" cy="30" r="7" fill="url(#coin3)" opacity="0.8">
    <animateTransform attributeName="transform" type="translate" values="0,0; 0,-5; 0,0" dur="3.5s" repeatCount="indefinite"/>
  </circle>
  <rect x="40" y="130" width="12" height="50" rx="3" fill="url(#bar1)" opacity="0.7">
    <animate attributeName="height" values="50;60;50" dur="2s" repeatCount="indefinite"/>
    <animate attributeName="y" values="130;120;130" dur="2s" repeatCount="indefinite"/>
  </rect>
  <rect x="58" y="100" width="12" height="80" rx="3" fill="url(#bar2)" opacity="0.7">
    <animate attributeName="height" values="80;70;80" dur="2.3s" repeatCount="indefinite"/>
    <animate attributeName="y" values="100;110;100" dur="2.3s" repeatCount="indefinite"/>
  </rect>
  <rect x="76" y="115" width="12" height="65" rx="3" fill="url(#bar3)" opacity="0.7">
    <animate attributeName="height" values="65;75;65" dur="1.8s" repeatCount="indefinite"/>
    <animate attributeName="y" values="115;105;115" dur="1.8s" repeatCount="indefinite"/>
  </rect>
  <g transform="translate(245, 140)">
    <rect x="0" y="10" width="24" height="28" rx="6" fill="url(#bag)" opacity="0.85">
      <animateTransform attributeName="transform" type="rotate" values="0 12 20; -3 12 20; 0 12 20" dur="4s" repeatCount="indefinite"/>
    </rect>
    <path d="M6 10 L12 0 L18 10" fill="url(#bag)" opacity="0.85"/>
  </g>
  <defs>
    <linearGradient id="bldg" x1="100" y1="80" x2="220" y2="200">
      <stop offset="0%" stop-color="#5eead4"/><stop offset="100%" stop-color="#0d9488"/>
    </linearGradient>
    <linearGradient id="roof" x1="100" y1="80" x2="220" y2="100">
      <stop offset="0%" stop-color="#6366f1"/><stop offset="100%" stop-color="#a78bfa"/>
    </linearGradient>
    <linearGradient id="awn" x1="95" y1="76" x2="240" y2="86">
      <stop offset="0%" stop-color="#f59e0b"/><stop offset="100%" stop-color="#ef4444"/>
    </linearGradient>
    <linearGradient id="sign" x1="130" y1="56" x2="190" y2="74">
      <stop offset="0%" stop-color="#6366f1"/><stop offset="100%" stop-color="#8b5cf6"/>
    </linearGradient>
    <linearGradient id="coin1" x1="235" y1="40" x2="250" y2="60">
      <stop offset="0%" stop-color="#fbbf24"/><stop offset="100%" stop-color="#f59e0b"/>
    </linearGradient>
    <linearGradient id="coin2" x1="45" y1="62" x2="58" y2="78">
      <stop offset="0%" stop-color="#fbbf24"/><stop offset="100%" stop-color="#f59e0b"/>
    </linearGradient>
    <linearGradient id="coin3" x1="195" y1="23" x2="207" y2="37">
      <stop offset="0%" stop-color="#fcd34d"/><stop offset="100%" stop-color="#f59e0b"/>
    </linearGradient>
    <linearGradient id="bar1" x1="40" y1="130" x2="52" y2="180">
      <stop offset="0%" stop-color="#5eead4"/><stop offset="100%" stop-color="#0d9488"/>
    </linearGradient>
    <linearGradient id="bar2" x1="58" y1="100" x2="70" y2="180">
      <stop offset="0%" stop-color="#a78bfa"/><stop offset="100%" stop-color="#6366f1"/>
    </linearGradient>
    <linearGradient id="bar3" x1="76" y1="115" x2="88" y2="180">
      <stop offset="0%" stop-color="#fbbf24"/><stop offset="100%" stop-color="#f59e0b"/>
    </linearGradient>
    <linearGradient id="bag" x1="245" y1="0" x2="270" y2="175">
      <stop offset="0%" stop-color="#fb7185"/><stop offset="100%" stop-color="#e11d48"/>
    </linearGradient>
  </defs>
</svg>
"""


def inject_auth_theme():
    """Inject the colorful auth page theme CSS + hide default Streamlit chrome."""
    st.markdown(AUTH_CSS, unsafe_allow_html=True)


def _icon(path: str, color: str) -> str:
    """A small inline SVG glyph on a tinted tile (icon shortcodes don't render inside raw HTML)."""
    return (f'<div class="dot" style="background:{color}22;border:1px solid {color}55">'
            f'<svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" '
            f'stroke-linejoin="round">{path}</svg></div>')


# What Duka Copilot does for an owner, shown as notifications sliding in one by one.
# These describe features (example notifications), not real account data.
_FEED = [
    ('<path d="M12 19V5M5 12l7-7 7 7"/>', "#5eead4", "M-Pesa payment received", "Recorded and categorised as a sale", "just now"),
    ('<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M16 3v4M8 3v4M4 11h16"/>', "#fbbf24",
     "Rent due in 3 days", "Reminder set; nothing is paid without your PIN", "2 min"),
    ('<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/>', "#a78bfa", "Cash forecast updated", "Next 14 days checked against your buffer", "5 min"),
    ('<path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/>', "#f9a8d4", "Stock running low", "Reorder suggested for 2 products", "12 min"),
]


def render_illustration():
    """Right-hand panel of the login / sign-up pages: animated shop, a live-looking
    feed of what Duka Copilot does, and trust badges. All motion stops for users who
    prefer reduced motion."""
    notes = "".join(
        f'<div class="duka-note">{_icon(path, color)}<div><b>{title}</b><span>{body}</span></div>'
        f'<div class="when">{when}</div></div>'
        for path, color, title, body, when in _FEED)
    html_content = (
        '<div class="duka-side">'
        f'<div class="duka-art">{SHOP_ILLUSTRATION}</div>'
        '<h2>Your business, amplified</h2>'
        '<p class="lede">Duka Copilot reads your M-Pesa statement, keeps your books, warns you before cash runs short '
        'and reminds you of bills — in English or Kiswahili.</p>'
        f'<div class="duka-feed">{notes}</div>'
        '<div class="duka-trust"><span>Names stored as tokens</span><span>Payments need your PIN</span>'
        '<span>Works in Kiswahili</span></div>'
        '</div>'
    )
    st.markdown(html_content, unsafe_allow_html=True)


def render_brand_header():
    """Render the Duka Copilot brand header inside the glass card."""
    html_content = ('<div class="duka-logo-wrap" style="text-align:center; margin-bottom:1rem;">' + DUKA_LOGO_SVG
                    + '</div><div class="auth-brand">Duka Copilot</div>'
                    '<div class="auth-tagline">Smart books for African micro-businesses</div>')
    st.markdown(html_content, unsafe_allow_html=True)


def render_progress_indicator(step: int, total_steps: int):
    """Render a visual progress indicator for multi-step forms."""
    steps_html = ""
    for i in range(1, total_steps + 1):
        status = "active" if i == step else ("done" if i < step else "")
        steps_html += f'<div class="auth-progress-step {status}">{i}</div>'
        if i < total_steps:
            connector_status = "done" if i < step else ""
            steps_html += f'<div class="auth-progress-connector {connector_status}"></div>'
    
    st.markdown(f'<div class="auth-progress">{steps_html}</div>', unsafe_allow_html=True)


def render_authenticated_hero(display_name: str = "", business_profile: dict | None = None):
    """Compact landing-style hero for pages where is_auth == true.

    Shown above the chat/nav hub instead of the full public landing page —
    same visual language (gradient hero, glass chip) but personalised and
    without Login/Sign Up CTAs, since the viewer is already authenticated.

    Icon shortcodes (:material/...:) only render inside Streamlit's own
    markdown/widget text — never inside a raw HTML string passed through
    unsafe_allow_html — so the icon-bearing lines are real st.markdown/
    st.caption calls, sandwiched between opening/closing <div> tags that
    carry the gradient box styling (the same technique already used for
    the CTA button rows below in this file).
    """
    first_name = html.escape((display_name or "there").split(" ")[0])

    if business_profile:
        icon = business_profile.get("icon", ":material/storefront:")
        name = html.escape(business_profile.get("name", "Active business"))
        sector = html.escape(business_profile.get("sector", ""))
        chip_text = f"{icon} {name}" + (f" · {sector}" if sector else "")
    else:
        chip_text = ":material/info: No business loaded — pick a sample SME or upload a statement"

    st.markdown('<div class="dashboard-hero">', unsafe_allow_html=True)
    st.markdown(f"#### :material/waving_hand: Welcome back, {first_name}")
    st.caption("Here's the state of your business right now.")
    st.markdown('<div class="business-chip">', unsafe_allow_html=True)
    st.markdown(chip_text)
    st.markdown('</div></div>', unsafe_allow_html=True)


def render_landing():
    """Render the beautiful landing page welcoming new and returning users."""
    inject_auth_theme()
    
    # Hero section
    st.markdown("""
    <div class="landing-hero">
        <h1>Duka Copilot</h1>
        <p>Smart books for African micro-businesses</p>
        <p style="font-size: 1rem; color: #94a3b8; margin-top: 1rem;">
            Manage your cash flow, understand your customers, and grow with confidence.
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # CTA Buttons
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<div style='text-align: center; display: flex; gap: 1rem; justify-content: center;'>", unsafe_allow_html=True)
        col_login, col_signup = st.columns(2)
        with col_login:
            if st.button(":material/login: Log In", width="stretch", key="btn_login_cta"):
                st.switch_page("app_pages/Login.py")
        with col_signup:
            if st.button(":material/person_add: Sign Up", width="stretch", key="btn_signup_cta"):
                st.switch_page("app_pages/Sign_Up.py")
        st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Features section
    st.markdown("""
    <h2 style="text-align: center; color: #e2e8f0; font-size: 2rem; margin: 2rem 0 1rem 0;">
        Everything you need to run your business
    </h2>
    <p style="text-align: center; color: #cbd5e1; font-size: 1.05rem; margin-bottom: 2rem;">
        Built for African SMEs, powered by AI
    </p>
    """, unsafe_allow_html=True)
    
    features = [
        (":material/analytics:", "Real-time Analytics",
         "Track revenue, expenses, margins, and profitability in real-time. Understand your business performance instantly."),
        (":material/trending_up:", "Cashflow Forecasting",
         "AI-powered forecasts predict your cash position with Monte Carlo simulations. Never get caught off guard."),
        (":material/groups:", "Customer Intelligence",
         "Identify your top customers, spot payment risks, and optimize your credit decisions automatically."),
        (":material/show_chart:", "Working Capital",
         "Manage receivables and payables efficiently. Get smart reminders and aging analysis out of the box."),
        (":material/account_balance:", "Smart Financing",
         "Compare loan options from digital lenders. See true rates, cash fit, and repayment terms side-by-side."),
        (":material/inventory_2:", "Inventory Management",
         "Track stock levels, optimize reorders, and reduce waste with intelligent inventory insights."),
    ]

    # Icon shortcodes only render in Streamlit's own markdown/widget text,
    # never inside raw HTML — so each card is a real st.container, not a
    # hand-rolled <div>.
    for row_start in range(0, len(features), 3):
        row = features[row_start:row_start + 3]
        cols = st.columns(3)
        for col, (icon, title, body) in zip(cols, row):
            with col:
                with st.container(border=True):
                    st.markdown(f"#### {icon} {title}")
                    st.markdown(body)
    
    st.markdown("---")
    
    # Stats section
    st.markdown("""
    <h2 style="text-align: center; color: #e2e8f0; font-size: 1.8rem; margin: 2rem 0 1rem 0;">
        Trusted by thousands of African businesses
    </h2>
    """, unsafe_allow_html=True)
    
    stat1, stat2, stat3, stat4 = st.columns(4)
    
    with stat1:
        st.markdown("""
        <div class="stat-box">
            <div class="number">2,500+</div>
            <div class="label">Active Businesses</div>
        </div>
        """, unsafe_allow_html=True)
    
    with stat2:
        st.markdown("""
        <div class="stat-box">
            <div class="number">$450M</div>
            <div class="label">Transactions Processed</div>
        </div>
        """, unsafe_allow_html=True)
    
    with stat3:
        st.markdown("""
        <div class="stat-box">
            <div class="number">98%</div>
            <div class="label">Uptime</div>
        </div>
        """, unsafe_allow_html=True)
    
    with stat4:
        st.markdown("""
        <div class="stat-box">
            <div class="number">15+</div>
            <div class="label">Countries</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Testimonials
    st.markdown("""
    <h2 style="text-align: center; color: #e2e8f0; font-size: 1.8rem; margin: 2rem 0 1rem 0;">
        What business owners are saying
    </h2>
    """, unsafe_allow_html=True)
    
    testimonials = [
        ("Duka Copilot has transformed how I manage my business. I used to worry about cash flow, "
         "but now I have real-time insights. It's like having a CFO in my pocket!",
         "Amina K., Grocery Retailer, Nairobi"),
        ("The forecasting feature has saved me thousands. I can now plan inventory better "
         "and make smarter decisions about which customers to extend credit to.",
         "Otieno M., Transport Business, Kisumu"),
        ("Setting up was incredibly easy, and the team is always there to help. Best "
         "business tool I've ever used for my salon. Highly recommended!",
         "Grace W., Salon Owner, Dar es Salaam"),
        ("The AI insights help me understand patterns I would have missed. My profit "
         "margins are up 22% since I started using Duka Copilot.",
         "James N., Logistics SME, Kampala"),
    ]

    stars_md = ":material/star: " * 5
    for row_start in range(0, len(testimonials), 2):
        row = testimonials[row_start:row_start + 2]
        cols = st.columns(2)
        for col, (quote, author) in zip(cols, row):
            with col:
                with st.container(border=True):
                    st.markdown(stars_md)
                    st.markdown(f'<div class="testimonial-quote"><em>"{html.escape(quote)}"</em></div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="testimonial-author">{html.escape(author)}</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Final CTA
    st.markdown("""
    <div style="text-align: center; padding: 3rem 2rem; background: linear-gradient(135deg, rgba(13, 148, 136, 0.1), rgba(99, 102, 241, 0.1)); border-radius: 24px; border: 1px solid rgba(255, 255, 255, 0.1); margin: 2rem 0;">
        <h2 style="color: #e2e8f0; margin: 0 0 1rem 0;">Ready to transform your business?</h2>
        <p style="color: #cbd5e1; font-size: 1.1rem; margin: 0 0 2rem 0;">
            Join thousands of African entrepreneurs who are already using Duka Copilot to build smarter businesses.
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<div style='display: flex; gap: 1rem; justify-content: center;'>", unsafe_allow_html=True)
        col_login2, col_signup2 = st.columns(2)
        with col_login2:
            if st.button(":material/login: Log In Now", width="stretch", key="btn_login_cta_2"):
                st.switch_page("app_pages/Login.py")
        with col_signup2:
            if st.button(":material/person_add: Get Started", width="stretch", key="btn_signup_cta_2"):
                st.switch_page("app_pages/Sign_Up.py")
        st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Footer
    st.markdown("""
    <div style="text-align: center; color: #64748b; font-size: 0.9rem; padding: 2rem 0; border-top: 1px solid rgba(255, 255, 255, 0.1);">
        <p style="margin: 0.5rem 0;">
            Built with care in Nairobi for African businesses
        </p>
        <p style="margin: 0.5rem 0;">
            <a href="#" style="color: #5eead4; text-decoration: none;">Privacy</a> | 
            <a href="#" style="color: #5eead4; text-decoration: none;">Terms</a> | 
            <a href="#" style="color: #5eead4; text-decoration: none;">Support</a>
        </p>
        <p style="margin: 1rem 0 0 0; color: #475569;">v1.0.0 | © 2026 Duka Copilot. All rights reserved.</p>
    </div>
    """, unsafe_allow_html=True)

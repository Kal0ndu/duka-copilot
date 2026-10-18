

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

.auth-glass-card {
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
.auth-glass-card label {
    color: #e2e8f0 !important;
    font-weight: 500 !important;
    margin-bottom: 0.5rem !important;
    font-size: 0.95rem !important;
}

.auth-glass-card input {
    background: rgba(255, 255, 255, 0.08) !important;
    border: 1px solid rgba(255, 255, 255, 0.2) !important;
    border-radius: 12px !important;
    color: #f1f5f9 !important;
    padding: 0.85rem 1.25rem !important;
    font-size: 0.95rem !important;
    transition: all 0.2s ease !important;
}

.auth-glass-card input::placeholder {
    color: #64748b !important;
}

.auth-glass-card input:focus {
    border-color: #5eead4 !important;
    background: rgba(255, 255, 255, 0.12) !important;
    box-shadow: 0 0 0 3px rgba(94, 234, 212, 0.15) !important;
}

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
.auth-glass-card .stButton > button {
    background: rgba(255, 255, 255, 0.08) !important;
    border: 1px solid rgba(255, 255, 255, 0.2) !important;
    border-radius: 12px !important;
    color: #e2e8f0 !important;
    font-weight: 500 !important;
    padding: 0.75rem 1.25rem !important;
    transition: all 0.3s ease !important;
    font-size: 0.9rem !important;
}

.auth-glass-card .stButton > button:hover {
    background: rgba(255, 255, 255, 0.12) !important;
    border-color: rgba(255, 255, 255, 0.35) !important;
}

/* Alerts and messages */
.auth-glass-card div[data-testid="stAlert"] {
    border-radius: 12px !important;
    padding: 1rem !important;
}

.auth-glass-card div[data-testid="stAlert"][kind="error"] {
    background: rgba(239, 68, 68, 0.15) !important;
    border: 1px solid rgba(239, 68, 68, 0.3) !important;
    color: #fca5a5 !important;
}

.auth-glass-card div[data-testid="stAlert"][kind="success"] {
    background: rgba(34, 197, 94, 0.15) !important;
    border: 1px solid rgba(34, 197, 94, 0.3) !important;
    color: #86efac !important;
}

.auth-glass-card div[data-testid="stAlert"][kind="info"] {
    background: rgba(59, 130, 246, 0.15) !important;
    border: 1px solid rgba(59, 130, 246, 0.3) !important;
    color: #93c5fd !important;
}

.auth-glass-card div[data-testid="stAlert"][kind="warning"] {
    background: rgba(245, 158, 11, 0.15) !important;
    border: 1px solid rgba(245, 158, 11, 0.3) !important;
    color: #fcd34d !important;
}

/* Divider */
.auth-glass-card hr {
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
.auth-glass-card a {
    color: #5eead4 !important;
    text-decoration: none;
    font-weight: 500;
}

.auth-glass-card a:hover {
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
    .auth-glass-card {
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


def render_illustration():
    """Render the right-side illustration panel with animated SVG."""
    html_content = '<div class="auth-illustration">' + SHOP_ILLUSTRATION + '<h2>Your Business, Amplified</h2><p>Smart bookkeeping, cashflow insights, and inventory management — all in one place.</p></div>'
    st.markdown(html_content, unsafe_allow_html=True)


def render_brand_header():
    """Render the Duka brand header inside the glass card."""
    html_content = '<div style="text-align:center; margin-bottom:1rem;">' + DUKA_LOGO_SVG + '</div><div class="auth-brand">Duka</div><div class="auth-tagline">Smart books for African micro-businesses</div>'
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
        <h1>Duka</h1>
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
            if st.button(":material/login: Log In", use_container_width=True, key="btn_login_cta"):
                st.switch_page("pages/Login.py")
        with col_signup:
            if st.button(":material/person_add: Sign Up", use_container_width=True, key="btn_signup_cta"):
                st.switch_page("pages/Sign_Up.py")
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
        ("Duka has transformed how I manage my business. I used to worry about cash flow, "
         "but now I have real-time insights. It's like having a CFO in my pocket!",
         "Amina K., Grocery Retailer, Nairobi"),
        ("The forecasting feature has saved me thousands. I can now plan inventory better "
         "and make smarter decisions about which customers to extend credit to.",
         "Otieno M., Transport Business, Kisumu"),
        ("Setting up was incredibly easy, and the team is always there to help. Best "
         "business tool I've ever used for my salon. Highly recommended!",
         "Grace W., Salon Owner, Dar es Salaam"),
        ("The AI insights help me understand patterns I would have missed. My profit "
         "margins are up 22% since I started using Duka.",
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
            Join thousands of African entrepreneurs who are already using Duka to build smarter businesses.
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<div style='display: flex; gap: 1rem; justify-content: center;'>", unsafe_allow_html=True)
        col_login2, col_signup2 = st.columns(2)
        with col_login2:
            if st.button(":material/login: Log In Now", use_container_width=True, key="btn_login_cta_2"):
                st.switch_page("pages/Login.py")
        with col_signup2:
            if st.button(":material/person_add: Get Started", use_container_width=True, key="btn_signup_cta_2"):
                st.switch_page("pages/Sign_Up.py")
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
        <p style="margin: 1rem 0 0 0; color: #475569;">v1.0.0 | © 2026 Duka. All rights reserved.</p>
    </div>
    """, unsafe_allow_html=True)

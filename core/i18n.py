"""Internationalization (i18n): Language detection and translation for Swahili/English."""
from typing import Optional, Dict, Any
from enum import Enum
import re


class Language(Enum):
    """Supported languages."""
    ENGLISH = "en"
    SWAHILI = "sw"


class I18n:
    """Translation manager for Duka Copilot with automatic language detection."""
    
    # Swahili translations for common UI strings and advice
    TRANSLATIONS = {
        # Navigation & UI elements
        "Dashboard": {"sw": "Muhtasari"},
        "Upload Statement": {"sw": "Pakia Taarifa ya M-Pesa"},
        "Analytics": {"sw": "Uchambuzi"},
        "Cashflow Forecast": {"sw": "Utabiri wa Mzunguko wa Pesa"},
        "Financing": {"sw": "Mikopo"},
        "Standing Orders": {"sw": "Malipo ya Kudumu"},
        "Chat": {"sw": "Mazungumzo"},
        "Business Setup": {"sw": "Mipangilio ya Biashara"},
        
        # Common metrics & terms
        "Revenue": {"sw": "Mapato"},
        "Expenses": {"sw": "Matumizi"},
        "Profit": {"sw": "Faida"},
        "Balance": {"sw": "Salio"},
        "Cash Flow": {"sw": "Mzunguko wa Pesa"},
        "Forecast": {"sw": "Utabiri"},
        "Loan": {"sw": "Mkopo"},
        "Interest": {"sw": "Riba"},
        "Fee": {"sw": "Ada"},
        "Payment": {"sw": "Malipo"},
        
        # Advice & guidance messages
        "Upload your M-Pesa statement to get started": {
            "sw": "Pakia taarifa yako ya M-Pesa ili kuanza"
        },
        "No statement loaded yet": {
            "sw": "Hakuna taarifa iliyopakiwa bado"
        },
        "Your business health is strong": {
            "sw": "Afya ya biashara yako ni nzuri"
        },
        "Monitor your cash flow closely": {
            "sw": "Fuatilia mzunguko wa pesa zako kwa karibu"
        },
        "Consider reducing personal withdrawals": {
            "sw": "Fikiria kupunguza pesa unazotoa kwa matumizi binafsi"
        },
        "Your balance forecast shows a shortfall": {
            "sw": "Utabiri wa salio lako unaonyesha upungufu"
        },
        "Compare digital credit options": {
            "sw": "Linganisha mikopo ya kidijitali"
        },
    }
    
    # Loan advice translations
    LOAN_ADVICE = {
        "en": {
            "total_cost_of_credit": "Total Cost of Credit (interest + fees)",
            "monthly_repayment": "Monthly repayment as % of profit",
            "check_cash_flow": "Check if the loan fits your forecast",
            "recommended_max": "Recommended: monthly payment ≤ 15% of profit",
            "keep_buffer": "Keep a safety buffer of 3 days of expenses",
        },
        "sw": {
            "total_cost_of_credit": "Jumla ya Gharama za Mkopo (riba + ada)",
            "monthly_repayment": "Malipo ya kila mwezi kama % ya faida",
            "check_cash_flow": "Angalia kama mkopo unatoshea katika utabiri wako",
            "recommended_max": "Inapendekezwa: malipo ya kila mwezi yasizidi 15% ya faida",
            "keep_buffer": "Weka akiba ya usalama ya matumizi ya siku 3",
        }
    }
    
    # Offline helper advice
    OFFLINE_ADVICE = {
        "en": {
            "welcome": "👋 Welcome to Duka Copilot!",
            "offline_mode": "I'm temporarily running in offline mode (no API connection). I can still help with basic guidance:",
            "what_i_can_do": "What I can do:",
            "answer_questions": "Answer questions about cash flow, loans, inventory, and more",
            "guide_features": "Guide you through using Duka Copilot features",
            "explain_metrics": "Explain financial metrics and best practices",
            "to_unlock_ai": "To unlock full AI features:",
            "check_api_key": "1. Check your LLM_API_KEY configuration",
            "check_internet": "2. Ensure you have internet connectivity",
            "ask_question": "3. Or ask me something like: 'How do I get started?'",
        },
        "sw": {
            "welcome": "👋 Karibu Duka Copilot!",
            "offline_mode": "Kwa sasa ninafanya kazi bila huduma ya AI (hakuna muunganisho). Bado ninaweza kusaidia kwa takwimu zako:",
            "what_i_can_do": "Ninachoweza kufanya:",
            "answer_questions": "Kujibu maswali kuhusu mzunguko wa pesa, mikopo, bidhaa na mengine",
            "guide_features": "Kukuongoza kutumia sehemu za Duka Copilot",
            "explain_metrics": "Kueleza vipimo vya fedha na mbinu bora",
            "to_unlock_ai": "Kuwasha AI kamili:",
            "check_api_key": "1. Angalia LLM_API_KEY kwenye mipangilio",
            "check_internet": "2. Hakikisha una mtandao",
            "ask_question": "3. Au niulize kitu kama: 'Nianze vipi?'",
        }
    }
    
    # Category translations
    CATEGORY_NAMES = {
        "SALES_TILL": {"sw": "Mauzo (Till)"},
        "SALES_TRANSFER": {"sw": "Mauzo (kutumiwa pesa)"},
        "STOCK_PURCHASES": {"sw": "Ununuzi wa Bidhaa"},
        "RENT": {"sw": "Kodi ya Nyumba"},
        "UTILITIES": {"sw": "Umeme na Maji"},
        "WAGES": {"sw": "Mishahara"},
        "TRANSPORT": {"sw": "Usafiri"},
        "AIRTIME_DATA": {"sw": "Muda wa Maongezi na Data"},
        "SCHOOL_FEES": {"sw": "Karo ya Shule"},
        "LOAN_DISBURSEMENT": {"sw": "Mkopo Uliopokelewa"},
        "LOAN_REPAYMENT": {"sw": "Marejesho ya Mkopo"},
        "OVERDRAFT_FEE": {"sw": "Ada ya Overdraft"},
        "TXN_CHARGES": {"sw": "Ada za Muamala"},
        "REPAIRS": {"sw": "Matengenezo"},
        "LICENSE_TAX": {"sw": "Leseni na Kodi"},
        "PERSONAL_WITHDRAWAL": {"sw": "Kutoa Pesa Binafsi"},
        "FAMILY_TRANSFER": {"sw": "Pesa kwa Familia"},
        "UNCATEGORISED": {"sw": "Haijapangwa"},
    }
    
    @classmethod
    def detect_language(cls, text: str) -> Language:
        """Detect language from user input using simple heuristics.
        
        Looks for Swahili keywords and patterns.
        Returns Language.SWAHILI if detected, otherwise Language.ENGLISH.
        """
        text_lower = text.lower()
        
        # Strong Swahili indicators
        strong_sw_patterns = [
            r"\bpesa\b", r"\bfedha\b", r"\bbiashara\b", r"\bmkopo\b",
            r"\briba\b", r"\bvipi\b", r"\bkwanini\b", r"\basante\b",
            r"\btaarifa\b", r"\bpakia\b", r"\bkuanza\b", r"\bniaje\b",
            r"\bnilipe\b", r"\blipa\b", r"\bshilingi\b", r"\binaendeleaje\b",
            r"\bnitakosa\b", r"\butabiri\b", r"\bmikopo\b", r"\bmatumizi\b",
            r"\bfaida\b", r"\bmauzo\b", r"\bsalio\b", r"\bzijazo\b", r"\bhabari\b",
        ]
        
        # Check for strong indicators first
        for pattern in strong_sw_patterns:
            if re.search(pattern, text_lower):
                return Language.SWAHILI
        
        # Common Swahili words
        common_sw_patterns = [
            r"\bkazi\b", r"\bhabari\b", r"\bsimu\b", r"\bkaribu\b",
            r"\bnini\b", r"\bkwenye\b", r"\bkwa\b", r"\bna\b",
            r"\bwapi\b", r"\bvipi\b", r"\bkuna\b", r"\buna\b",
            r"\bina\b", r"\bya\b", r"\bni\b", r"\byangu\b", r"\bwiki\b",
            r"\bje\b", r"\bajili\b", r"\bkiasi\b",
        ]
        
        # Count common patterns
        common_count = sum(1 for pattern in common_sw_patterns if re.search(pattern, text_lower))
        if common_count >= 2:
            return Language.SWAHILI
        
        return Language.ENGLISH
    
    @classmethod
    def t(cls, key: str, lang: Optional[Language] = None) -> str:
        """Translate a key to the target language.
        
        Args:
            key: Translation key (usually English phrase)
            lang: Target language (defaults to ENGLISH if not provided)
        
        Returns:
            Translated string if available, otherwise the key as-is.
        """
        if lang is None:
            lang = Language.ENGLISH
        
        if key not in cls.TRANSLATIONS:
            return key
        
        translations = cls.TRANSLATIONS[key]
        if lang.value in translations:
            return translations[lang.value]
        
        return key
    
    @classmethod
    def translate_category(cls, category_code: str, lang: Optional[Language] = None) -> str:
        """Translate transaction category name.
        
        Args:
            category_code: Category code (e.g., SALES_TILL)
            lang: Target language
        
        Returns:
            Translated category name.
        """
        if lang is None:
            lang = Language.ENGLISH
        
        if category_code not in cls.CATEGORY_NAMES:
            return category_code
        
        names = cls.CATEGORY_NAMES[category_code]
        if lang.value in names:
            return names[lang.value]
        
        return category_code
    
    @classmethod
    def translate_advice(cls, section: str, key: str, lang: Optional[Language] = None) -> str:
        """Translate advice strings (loan advice, offline guidance, etc).
        
        Args:
            section: Section name (e.g., "LOAN_ADVICE", "OFFLINE_ADVICE")
            key: Key within that section
            lang: Target language
        
        Returns:
            Translated advice string.
        """
        if lang is None:
            lang = Language.ENGLISH
        
        advice_dict = getattr(cls, section, {})
        if lang.value not in advice_dict:
            return key
        
        return advice_dict[lang.value].get(key, key)
    
    @classmethod
    def format_number(cls, value: float, lang: Optional[Language] = None) -> str:
        """Format a number according to language conventions.
        
        Args:
            value: Number to format
            lang: Target language
        
        Returns:
            Formatted number string.
        """
        if lang is None or lang == Language.ENGLISH:
            return f"{value:,.0f}"
        elif lang == Language.SWAHILI:
            # Swahili uses comma for thousands and period for decimal
            return f"{value:,.0f}"
        
        return f"{value:,.0f}"
    
    @classmethod
    def format_currency(cls, amount_kes: float, lang: Optional[Language] = None) -> str:
        """Format currency with language-appropriate prefix.
        
        Args:
            amount_kes: Amount in KES
            lang: Target language
        
        Returns:
            Formatted currency string.
        """
        if lang is None or lang == Language.ENGLISH:
            return f"KES {amount_kes:,.0f}"
        elif lang == Language.SWAHILI:
            return f"KES {amount_kes:,.0f}"  # Currency code stays same
        
        return f"KES {amount_kes:,.0f}"

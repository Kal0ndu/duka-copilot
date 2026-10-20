---
name: crisp-ui
description: Design rules for a crisp, professional Streamlit UI for Duka Copilot. Use whenever creating or changing app.py or any interface.
---

# Crisp UI rules for Duka Copilot

Follow every rule below when creating or changing `app.py` or any other interface.
A UI change must never change a calculation or any security behaviour.

## 1. Hierarchy
- The most important thing on each tab comes first.
- Alerts and the **true position** go at the top; details go below.

## 2. Consistency
- One accent colour plus neutral greys. Status colours (red/amber/green) only for status,
  always with an icon or words as well.
- Consistent spacing between sections.
- The same card style for every metric.

## 3. Numbers
- Always `KES 12,345`, with thousand separators.
- Negatives clearly marked: `KES -37,967`, and shown in a warning style where it matters.
- No raw, unformatted tables: format every amount, date and percentage, and use
  plain column names.

## 4. Plain language
- Short labels a shop owner understands.
- A one-sentence takeaway under every chart.
- No jargon without a help tooltip (e.g. "true position", "effective annual cost").

## 5. States
- Friendly empty states ("No requests are waiting"), loading messages
  ("Working out your forecast...") and error messages.
- Never show a raw error or stack trace to the owner.

## 6. Charts
- A clear title, units on the axes (KES), the safety-buffer line labelled.
- Colour is never the only way meaning is shown: use line styles, labels or text too.
- A table view for anyone who can't read the chart.

## 7. Layout
- Works on a narrow laptop or phone width; nothing cluttered.
- At most about 5 metrics in a row (Streamlit stacks columns on narrow screens).

## 8. Language
- Swahili text can be longer: keep labels in columns short, let long text wrap,
  and check every screen in both English and Kiswahili.

## 9. Safety cues
- Anything that moves money (approving payments or loans, changing caps or payees)
  looks clearly different from read-only screens, and always says it needs the
  owner's PIN.

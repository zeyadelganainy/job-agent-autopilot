# Demo media

The README's hero points to **`docs/demo.gif`** — a screen recording of the workflow.
Replace it with an updated capture anytime; keep the same filename so the README hero
keeps working.

## What to capture

The most compelling single image is a side-by-side of the **input** (your Telegram
shortlist) and the **output** (a generated résumé). Capture both, then either combine
them into one `demo.png` or use them separately.

1. **`docs/demo.png`** *(hero — required)* — the headline shot. Easiest options:
   - a screenshot of the Telegram digest (numbered matches + Apply links), **or**
   - a side-by-side collage of the digest and an open `resume.docx`, **or**
   - a short screen-recording exported as a GIF (then reference `docs/demo.gif`).
2. *(optional)* `docs/digest.png` — just the Telegram digest.
3. *(optional)* `docs/resume.png` — a generated `resume.docx` open in Word.

## How to generate fresh output to screenshot

```bash
python bot.py        # then in Telegram: /scan  ->  /pick 1
```

The digest and the three files (`resume.docx`, `cover_letter.md`, `resume.md`) arrive
in your chat — screenshot the digest, and open `resume.docx` for the résumé shot.

> Tip: blur or use a throwaway value for your phone/email in screenshots if you'd
> rather not show personal contact details publicly.
